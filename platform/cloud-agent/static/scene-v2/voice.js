/* VelaGuard scene-v2 voice entry — real capture, explicit ASR dependency, no fake transcript. */
(function () {
  "use strict";

  var els = {};
  var opts = {};
  var config = {
    endpoint: null,
    method: "POST",
    field: "audio",
    timeoutMs: 25000,
    maxSeconds: 45,
    credentials: "same-origin"
  };

  var state = {
    mode: "idle",
    stream: null,
    recorder: null,
    chunks: [],
    startedAt: 0,
    tickTimer: 0,
    maxTimer: 0,
    abort: null,
    cancelled: false,
    configLoaded: false,
    configLoading: false,
    configError: false,
    returnFocus: null
  };

  function $(id) {
    return document.getElementById(id);
  }

  function clamp(value, min, max, fallback) {
    var number = Number(value);
    if (!isFinite(number)) {
      return fallback;
    }
    return Math.max(min, Math.min(max, Math.floor(number)));
  }

  function notify(voiceState) {
    if (typeof opts.onState === "function") {
      opts.onState(voiceState);
    }
  }

  function stopLabel() {
    return config.endpoint ? "停止并转写" : "停止录音";
  }

  function setMode(mode, status, hint) {
    state.mode = mode;
    els.pop.setAttribute("data-state", mode);
    els.status.textContent = status;
    if (hint) {
      els.hint.textContent = hint;
    }
    els.main.disabled = mode === "requesting" || mode === "stopping" || mode === "recognizing";
    els.cancel.hidden = !(mode === "listening" || mode === "requesting" || mode === "recognizing");

    var labels = {
      idle: "开始说话",
      requesting: "请求权限…",
      listening: stopLabel(),
      stopping: "正在结束…",
      recognizing: "识别中…",
      captured: "重新录音",
      error: "重试",
      unavailable: "重试检测",
      done: "再说一句"
    };
    els.main.textContent = labels[mode] || labels.idle;
    notify(mode);
  }

  function setEndpointLabel() {
    if (state.configError) {
      els.endpoint.textContent = "识别配置读取失败；当前只做采集，不转写，也不会生成猜测文字。";
      return;
    }
    if (!state.configLoaded) {
      els.endpoint.textContent = "识别配置读取中… 未完成前不会发起转写。";
      return;
    }
    if (config.endpoint) {
      els.endpoint.textContent = "识别端点：已配置（仅同源）。录音结束后上传转写；没有返回文字就报错。";
    } else {
      els.endpoint.textContent = "识别端点：未配置。录音不会转成文字，也不会调用 Web Speech 或本地假识别。";
    }
  }

  function loadConfig() {
    var url = opts.configUrl;
    if (state.configLoaded || state.configLoading) {
      return;
    }
    if (!url) {
      state.configLoaded = true;
      setEndpointLabel();
      return;
    }
    state.configLoading = true;
    fetch(url, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" }
    }).then(function (response) {
      if (!response.ok) {
        throw new Error("config_http");
      }
      return response.json();
    }).then(function (data) {
      state.configError = false;
      var rawEndpoint = data && data.endpoint;
      var endpoint = normalizeEndpoint(rawEndpoint);
      config.endpoint = endpoint;
      if (rawEndpoint && !endpoint) {
        state.configError = true;
      }
      config.method = data && data.method === "POST" ? "POST" : "POST";
      config.field = data && typeof data.field === "string" && data.field.trim() ? data.field.trim() : "audio";
      config.timeoutMs = clamp(data && data.timeoutMs, 5000, 60000, 25000);
      config.maxSeconds = clamp(data && data.maxSeconds, 5, 120, 45);
      config.credentials = "same-origin";
      state.configLoading = false;
      state.configLoaded = true;
      setEndpointLabel();
    }).catch(function () {
      config.endpoint = null;
      state.configLoading = false;
      state.configLoaded = true;
      state.configError = true;
      setEndpointLabel();
    });
  }

  function normalizeEndpoint(value) {
    if (typeof value !== "string" || !value.trim()) {
      return null;
    }
    try {
      var parsed = new URL(value, window.location.href);
      if (parsed.origin !== window.location.origin) {
        state.configError = true;
        return null;
      }
      return parsed.pathname + parsed.search;
    } catch (err) {
      state.configError = true;
      return null;
    }
  }

  function environmentIssue() {
    if (!window.isSecureContext) {
      return "当前页面不是安全上下文。麦克风需要 HTTPS 或 localhost；file:// 预览也不会被允许。";
    }
    if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function") {
      return "当前浏览器不提供麦克风采集接口。请改用受支持的浏览器，并使用底部文字输入。";
    }
    if (!window.MediaRecorder) {
      return "当前浏览器没有 MediaRecorder，无法采集音频。请改用文字输入。";
    }
    return "";
  }

  function open() {
    state.returnFocus = document.activeElement;
    els.pop.hidden = false;
    els.voiceBtn.setAttribute("aria-expanded", "true");
    if (!state.configLoaded) {
      loadConfig();
    }
    var issue = environmentIssue();
    if (issue) {
      setMode("unavailable", issue, "没有可用录音时，不会伪造识别结果；可直接使用文字输入。");
    } else if (state.mode === "idle" || state.mode === "unavailable") {
      setMode("idle", "点击下方按钮开始说话。录音只在本页处理；是否转写取决于同源识别服务。", "没有识别结果时，不会自动填入文字。");
    }
    window.requestAnimationFrame(function () {
      els.main.focus({ preventScroll: true });
    });
  }

  function close() {
    if (els.pop.hidden) {
      return;
    }
    resetCapture();
    els.pop.hidden = true;
    els.voiceBtn.setAttribute("aria-expanded", "false");
    setMode("idle", "点击下方按钮开始说话。录音只在本页处理；是否转写取决于同源识别服务。", "没有识别结果时，不会自动填入文字。");
    if (state.returnFocus && typeof state.returnFocus.focus === "function") {
      state.returnFocus.focus({ preventScroll: true });
    }
    state.returnFocus = null;
  }

  function resetCapture() {
    state.cancelled = true;
    if (state.abort) {
      try {
        state.abort.abort();
      } catch (err) {
        /* ignore */
      }
      state.abort = null;
    }
    stopTimers();
    if (state.recorder && state.recorder.state !== "inactive") {
      try {
        state.recorder.stop();
      } catch (err) {
        /* ignore */
      }
    }
    state.recorder = null;
    state.chunks = [];
    stopStream();
  }

  function stopStream() {
    if (state.stream) {
      var tracks = state.stream.getTracks();
      for (var i = 0; i < tracks.length; i += 1) {
        try {
          tracks[i].stop();
        } catch (err) {
          /* ignore */
        }
      }
      state.stream = null;
    }
  }

  function stopTimers() {
    if (state.tickTimer) {
      window.clearInterval(state.tickTimer);
      state.tickTimer = 0;
    }
    if (state.maxTimer) {
      window.clearTimeout(state.maxTimer);
      state.maxTimer = 0;
    }
  }

  function pickMimeType() {
    var candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/ogg"
    ];
    for (var i = 0; i < candidates.length; i += 1) {
      if (window.MediaRecorder && typeof window.MediaRecorder.isTypeSupported === "function" && window.MediaRecorder.isTypeSupported(candidates[i])) {
        return candidates[i];
      }
    }
    return "";
  }

  function start() {
    if (state.mode === "listening") {
      stop();
      return;
    }
    if (state.mode === "requesting" || state.mode === "recognizing" || state.mode === "stopping") {
      return;
    }
    var issue = environmentIssue();
    if (issue) {
      setMode("unavailable", issue, "没有可用录音时，不会伪造识别结果；可直接使用文字输入。");
      return;
    }

    state.cancelled = false;
    setMode("requesting", "正在请求麦克风权限…", "浏览器或页面策略可能直接拒绝；被拒绝时不会生成任何文字。");

    navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      },
      video: false
    }).then(function (stream) {
      if (state.cancelled) {
        stream.getTracks().forEach(function (track) {
          track.stop();
        });
        return;
      }
      state.stream = stream;
      beginRecording(stream);
    }).catch(function (error) {
      if (state.cancelled) {
        return;
      }
      handleMediaError(error);
    });
  }

  function beginRecording(stream) {
    var mimeType = pickMimeType();
    var recorder;
    try {
      recorder = mimeType ? new MediaRecorder(stream, { mimeType: mimeType }) : new MediaRecorder(stream);
    } catch (firstError) {
      try {
        recorder = new MediaRecorder(stream);
      } catch (secondError) {
        stopStream();
        setMode("error", "当前浏览器无法创建录音器。", "可改用键盘输入；没有录音就不会伪造识别结果。");
        return;
      }
    }

    state.recorder = recorder;
    state.chunks = [];
    state.startedAt = Date.now();

    recorder.ondataavailable = function (event) {
      if (event.data && event.data.size > 0) {
        state.chunks.push(event.data);
      }
    };
    recorder.onerror = function () {
      stopTimers();
      stopStream();
      setMode("error", "录音过程中出错，没有得到可用音频。", "可重试或改用键盘输入；页面不会补写文字。");
    };
    recorder.onstop = function () {
      finishRecording();
    };

    try {
      recorder.start(250);
    } catch (error) {
      stopStream();
      setMode("error", "录音器启动失败。", "可重试或改用键盘输入；页面不会补写文字。");
      return;
    }

    var maxSeconds = config.maxSeconds || 45;
    var label = stopLabel();
    setMode("listening", "正在听… 0 秒 / 最长 " + maxSeconds + " 秒。说完点“" + label + "”。", "录音只在本页内存中；取消会立即丢弃。");
    state.tickTimer = window.setInterval(function () {
      var seconds = Math.min(maxSeconds, Math.floor((Date.now() - state.startedAt) / 1000));
      els.status.textContent = "正在听… " + seconds + " 秒 / 最长 " + maxSeconds + " 秒。说完点“" + label + "”。";
    }, 500);
    state.maxTimer = window.setTimeout(function () {
      if (state.mode === "listening") {
        stop();
      }
    }, maxSeconds * 1000);
  }

  function stop() {
    if (!state.recorder || state.mode !== "listening") {
      return;
    }
    stopTimers();
    setMode("stopping", "正在结束录音…", "请稍候。");
    try {
      state.recorder.stop();
    } catch (error) {
      finishRecording();
    }
  }

  function finishRecording() {
    stopTimers();
    stopStream();

    if (els.pop.hidden) {
      state.recorder = null;
      state.chunks = [];
      return;
    }

    var recorder = state.recorder;
    var cancelled = state.cancelled;
    var mimeType = recorder && recorder.mimeType ? recorder.mimeType : "audio/webm";
    state.recorder = null;

    if (cancelled) {
      state.chunks = [];
      setMode("idle", "已取消，录音没有保留，也没有生成文字。", "没有识别结果时，不会自动填入文字。");
      return;
    }

    var blob = new Blob(state.chunks, { type: mimeType });
    state.chunks = [];
    if (!blob.size || blob.size < 600) {
      setMode("error", "没有采集到有效音频（录音为空）。", "请检查麦克风后重试，或改用键盘输入；页面不会补写文字。");
      return;
    }

    var seconds = Math.max(1, Math.round((Date.now() - state.startedAt) / 1000));
    if (!config.endpoint) {
      setMode("captured", "录音已结束（约 " + seconds + " 秒），但本页没有配置识别端点，未生成文字。请手动输入刚才说的内容。", "这是“已采集、未转写”，不是识别成功。");
      return;
    }
    recognize(blob, seconds);
  }

  function recognize(blob, seconds) {
    var controller = new AbortController();
    state.abort = controller;
    var timer = window.setTimeout(function () {
      try {
        controller.abort();
      } catch (err) {
        /* ignore */
      }
    }, config.timeoutMs);

    setMode("recognizing", "正在请求同源识别服务…", "没有返回文字就会报错，不会补猜。");
    var form = new FormData();
    var filename = blob.type && blob.type.indexOf("ogg") !== -1 ? "speech.ogg" : "speech.webm";
    form.append(config.field, blob, filename);
    var headers = { Accept: "application/json" };
    var token = typeof opts.getToken === "function" ? opts.getToken() : "";
    if (token) {
      headers.Authorization = "Bearer " + token;
    }

    fetch(config.endpoint, {
      method: config.method,
      body: form,
      credentials: config.credentials,
      headers: headers,
      signal: controller.signal
    }).then(function (response) {
      return response.text().then(function (text) {
        window.clearTimeout(timer);
        var payload = null;
        try {
          payload = JSON.parse(text);
        } catch (err) {
          payload = null;
        }
        if (!response.ok) {
          var httpError = new Error("asr_http");
          httpError.status = response.status;
          throw httpError;
        }
        return payload;
      });
    }).then(function (payload) {
      window.clearTimeout(timer);
      state.abort = null;
      if (state.cancelled || els.pop.hidden) {
        return;
      }
      if (!payload || typeof payload !== "object") {
        setMode("error", "识别服务返回的不是 JSON 对象，未生成文字。", "请维护者检查 ASR 接口；页面不会补写文字。");
        return;
      }
      if (payload.ok === false) {
        setMode("error", "识别服务明确返回失败，未生成文字。", "请稍后重试或改用键盘输入。");
        return;
      }
      var text = "";
      if (typeof payload.text === "string") {
        text = payload.text;
      } else if (typeof payload.transcript === "string") {
        text = payload.transcript;
      }
      text = text.trim();
      if (!text) {
        setMode("error", "识别服务返回了空文字；没有可编辑的草案。", "没有 ASR 文字时不会自动填入内容。");
        return;
      }
      setMode("done", "已转写（录音约 " + seconds + " 秒）。文字已放入底部草案，请核对后发送。", "识别结果可编辑；不会自动发送。");
      if (typeof opts.onText === "function") {
        opts.onText(text);
      }
      window.setTimeout(function () {
        if (state.mode === "done") {
          close();
        }
      }, 1200);
    }).catch(function (error) {
      window.clearTimeout(timer);
      state.abort = null;
      if (state.cancelled || els.pop.hidden) {
        return;
      }
      if (error && error.name === "AbortError") {
        setMode("error", "识别请求超时或被取消，未生成文字。", "可重试或改用键盘输入。");
      } else if (error && error.status) {
        setMode("error", "识别服务返回 HTTP " + error.status + "，未生成文字。", "请维护者检查同源 ASR 服务；页面不会补写文字。");
      } else {
        setMode("error", "识别服务不可达，未生成文字。", "请检查服务后重试，或改用键盘输入。");
      }
    });
  }

  function handleMediaError(error) {
    var name = error && error.name ? error.name : "";
    var message;
    if (name === "NotAllowedError" || name === "PermissionDeniedError" || name === "SecurityError") {
      message = "麦克风未获授权，或被页面的 Permissions-Policy 阻止。请在站点权限中允许麦克风；若响应头仍是 microphone=()，需要维护者为本页放开。";
    } else if (name === "NotFoundError" || name === "DevicesNotFoundError") {
      message = "没有检测到麦克风设备。请接入麦克风后重试，或改用键盘输入。";
    } else if (name === "NotReadableError" || name === "TrackStartError") {
      message = "麦克风被其他程序占用或系统拒绝读取。关闭占用程序后重试，或改用键盘输入。";
    } else if (name === "OverconstrainedError") {
      message = "麦克风不支持所需采集参数。请更换设备后重试，或改用键盘输入。";
    } else {
      message = "无法打开麦克风。请检查系统权限与设备连接，或改用键盘输入。";
    }
    setMode("error", message, "没有录音就不会有识别结果；页面不会伪造文字。");
  }

  function manualInput() {
    if (typeof opts.onManual === "function") {
      opts.onManual();
      return;
    }
    close();
    var input = $("chat-input");
    if (input) {
      input.focus({ preventScroll: true });
    }
  }

  function mainAction() {
    if (state.mode === "listening") {
      stop();
      return;
    }
    if (state.mode === "recognizing" || state.mode === "requesting" || state.mode === "stopping") {
      return;
    }
    start();
  }

  function cancel() {
    resetCapture();
    setMode("idle", "已取消，录音与识别请求都没有保留。", "没有识别结果时，不会自动填入文字。");
  }

  function bind() {
    els.voiceBtn = $("voice-btn");
    els.pop = $("voice-pop");
    els.status = $("voice-status");
    els.hint = $("voice-hint");
    els.main = $("voice-main");
    els.cancel = $("voice-cancel");
    els.manual = $("voice-manual");
    els.endpoint = $("voice-endpoint");
    els.close = $("voice-close");

    els.main.addEventListener("click", mainAction);
    els.cancel.addEventListener("click", cancel);
    els.close.addEventListener("click", close);
    els.manual.addEventListener("click", manualInput);
    els.pop.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close();
      }
    });
  }

  function init(options) {
    opts = options || {};
    bind();
    setMode("idle", "点击下方按钮开始说话。录音只在本页处理；是否转写取决于同源识别服务。", "没有识别结果时，不会自动填入文字。");
    loadConfig();
    setEndpointLabel();
  }

  window.VelaVoice = {
    init: init,
    open: open,
    close: close,
    isOpen: function () {
      return els.pop && !els.pop.hidden;
    }
  };
})();
