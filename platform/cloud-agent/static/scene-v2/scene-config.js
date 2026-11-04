/* VelaGuard scene-v2 local configuration. No secrets, no remote assets. */
(function () {
  "use strict";

  window.VelaSceneConfig = {
    /*
     * 正式场景图覆盖位。换图只改这里：
     *   asset: "/static/scene-v2/assets/<new-file>.svg|png",
     *   assetVersion: "交付日期或短哈希",
     *   assetSize: { w: 实际像素宽, h: 实际像素高 }。
     * 该文件是 1600×900 的矢量主视觉，构图与热点坐标同源，
     * 不再回退到旧的 scene-v2.png。
     */
    asset: "/static/scene-v2/assets/scene-hero.svg",
    assetVersion: "20261018-water-v13",
    assetSize: { w: 1600, h: 900 },
    assetPending: false,
    asrConfig: "/static/scene-v2/asr-config.json",
    spots: {
      "dam": { x: 27, y: 53, side: "right" },
      "building": { x: 86, y: 38, side: "left" }
    }
  };
})();


