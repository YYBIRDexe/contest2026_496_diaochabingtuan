from pathlib import Path
import math

from PIL import Image, ImageDraw, ImageFont


OUTPUT = Path(r"app/vela_mecanum/outputs\formation-error-curves.png")

square_targets = {
    "robot1": (-2.33, -0.65),
    "robot2": (-2.63, -0.01),
    "robot3": (-2.80, -0.48),
    "robot4": (-2.16, -0.18),
}
square_samples = {
    "robot1": [(-2.48, -1.02), (-2.48, -0.99), (-2.35, -0.69), (-2.354864, -0.708240)],
    "robot2": [(-2.52, 0.27), (-2.54, 0.23), (-2.628030, -0.015767)],
    "robot3": [(-2.47, -0.58), (-2.73, -0.48), (-2.751191, -0.444791)],
    "robot4": [(-2.33, -0.01), (-2.29, -0.05), (-2.20, -0.18), (-2.244666, -0.205742)],
}

line_targets = {
    "robot1": (-2.49, -1.065),
    "robot2": (-2.49, 0.435),
    "robot3": (-2.49, -0.565),
    "robot4": (-2.49, -0.065),
}
line_samples = {
    "robot1": [
        (-2.33, -0.73), (-2.37, -0.76), (-2.70, -1.04), (-2.70, -1.00),
        (-2.75, -1.06), (-2.71, -1.01), (-2.73, -1.02), (-2.69, -1.04),
        (-2.67, -1.04), (-2.64, -1.06), (-2.61, -1.07), (-2.614621, -1.072480),
    ],
    "robot2": [
        (-2.59, 0.19), (-2.54, 0.21), (-2.26, 0.50), (-2.28, 0.36),
        (-2.23, 0.43), (-2.27, 0.36), (-2.29, 0.40), (-2.33, 0.39),
        (-2.34, 0.39), (-2.385567, 0.396437),
    ],
    "robot3": [
        (-2.72, -0.47), (-2.65, -0.54), (-2.56, -0.55), (-2.57, -0.57),
        (-2.56, -0.55), (-2.53, -0.58), (-2.529998, -0.587120),
    ],
    "robot4": [
        (-2.28, -0.18), (-2.37, -0.13), (-2.43, -0.05), (-2.40, -0.09),
        (-2.42, -0.11), (-2.43, -0.12), (-2.42, -0.09), (-2.330406, -0.074449),
    ],
}


def errors(samples, target):
    return [math.hypot(x - target[0], y - target[1]) for x, y in samples]


def normalized_progress(count):
    if count == 1:
        return [1.0]
    return [index / (count - 1) for index in range(count)]


image = Image.new("RGB", (1600, 820), "white")
draw = ImageDraw.Draw(image)
font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 20)
small = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 17)
title_font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 27)
colors = {
    "robot1": "#3366cc",
    "robot2": "#dc3912",
    "robot3": "#109618",
    "robot4": "#990099",
}

draw.text((800, 18), "Formation target error from recorded progress samples", fill="#20242a", font=title_font, anchor="ma")

panels = (
    (70, 90, 750, 690, "Square test: converged", square_samples, square_targets,
     {"robot1": 0.070, "robot2": 0.018, "robot3": 0.050, "robot4": 0.092}),
    (850, 90, 1530, 690, "Synchronized line test: timed out", line_samples, line_targets,
     {"robot1": 0.135, "robot2": 0.105, "robot3": 0.045, "robot4": 0.170}),
)
maximum_error = 0.50
for left, top, right, bottom, title, samples_by_robot, targets, label_values in panels:
    draw.rectangle((left, top, right, bottom), outline="#9aa3ad", width=2)
    draw.text(((left + right) / 2, top - 42), title, fill="#20242a", font=font, anchor="ma")
    for tick in range(6):
        value = tick * 0.1
        y = bottom - value / maximum_error * (bottom - top)
        draw.line((left, y, right, y), fill="#e0e4e8", width=1)
        draw.text((left - 10, y), f"{value:.1f}", fill="#59636e", font=small, anchor="rm")
    reference_y = bottom - 0.10 / maximum_error * (bottom - top)
    for x in range(left, right, 16):
        draw.line((x, reference_y, min(x + 8, right), reference_y), fill="#666666", width=2)
    draw.text((right - 8, reference_y - 8), "0.10 m reference", fill="#555555", font=small, anchor="rs")
    for robot, samples in samples_by_robot.items():
        values = errors(samples, targets[robot])
        progress = normalized_progress(len(values))
        points = [
            (left + value * (right - left), bottom - error / maximum_error * (bottom - top))
            for value, error in zip(progress, values)
        ]
        draw.line(points, fill=colors[robot], width=4, joint="curve")
        for x, y in points:
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=colors[robot])
        label_y = bottom - label_values[robot] / maximum_error * (bottom - top)
        draw.text((right - 8, label_y), f"{robot} {values[-1]:.3f} m", fill=colors[robot], font=small, anchor="rs")
    draw.text(((left + right) / 2, bottom + 38), "Recorded progress, normalized", fill="#59636e", font=small, anchor="ma")

draw.text((70, 62), "Target error (m)", fill="#59636e", font=small, anchor="la")
draw.text((800, 775), "Samples come from controller progress output and the final AMCL check; intermediate unrecorded points are omitted.", fill="#59636e", font=small, anchor="ma")
image.save(OUTPUT)

for name, samples_by_robot, targets in (
    ("square", square_samples, square_targets),
    ("line", line_samples, line_targets),
):
    final = {robot: errors(samples, targets[robot])[-1] for robot, samples in samples_by_robot.items()}
    print(name, " ".join(f"{robot}={value:.3f}" for robot, value in final.items()))
