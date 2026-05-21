import cv2
import os
import numpy as np
import random
import csv


# --------------------------------------------------------
#   MICRO VARIATION FUNCTIONS (100% SAFE – NON-VISIBLE)
# --------------------------------------------------------

def micro_noise(img):
    noise = np.random.randint(0, 4, img.shape, dtype='uint8')
    return cv2.add(img, noise)


def micro_dither(img):
    dither = np.random.randint(-2, 2, img.shape, dtype='int16')
    out = img.astype(np.int16) + dither
    return np.clip(out, 0, 255).astype('uint8')


def micro_hsv_shift(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.int16)
    hsv[:, :, 0] = (hsv[:, :, 0] + random.randint(-1, 1)) % 180
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] + random.randint(-3, 3), 0, 255)
    hsv[:, :, 2] = np.clip(hsv[:, :, 2] + random.randint(-3, 3), 0, 255)
    return cv2.cvtColor(hsv.astype('uint8'), cv2.COLOR_HSV2BGR)


def micro_shift(img):
    M = np.float32([
        [1, 0, random.uniform(-0.4, 0.4)],
        [0, 1, random.uniform(-0.4, 0.4)]
    ])
    return cv2.warpAffine(
        img,
        M,
        (img.shape[1], img.shape[0]),
        borderMode=cv2.BORDER_REFLECT
    )


def micro_jpeg(img):
    quality = random.randint(85, 95)
    _, jpg = cv2.imencode(
        '.jpg',
        img,
        [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    )
    return cv2.imdecode(jpg, cv2.IMREAD_COLOR)


def apply_ultra_safe_variations(img):
    img = micro_noise(img)
    img = micro_dither(img)
    img = micro_hsv_shift(img)
    img = micro_shift(img)
    img = micro_jpeg(img)
    return img


# --------------------------------------------------------
#   MAIN FUNCTION (UNCHANGED FUNCTIONALITY)
# --------------------------------------------------------

def add_images_to_folders(
    base_image_paths,
    overlay_image_path,
    num_images,
    coordinates,
    folder_base_name
):
    output_directory = "images"
    os.makedirs(output_directory, exist_ok=True)

    folder_path = os.path.join(output_directory, folder_base_name)
    os.makedirs(folder_path, exist_ok=True)

    # 📄 CSV FILE PATH
    csv_path = os.path.join(folder_path, f"{folder_base_name}.csv")

    overlay_image = cv2.imread(overlay_image_path, cv2.IMREAD_UNCHANGED)
    overlay_h, overlay_w = overlay_image.shape[:2]

    image_counter = 1

    # 📝 CREATE CSV
    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["image_name", "url"])

        while image_counter <= num_images:
            for base_path in base_image_paths:
                if image_counter > num_images:
                    break

                base_img = cv2.imread(base_path)
                if base_img is None:
                    continue

                base_img = apply_ultra_safe_variations(base_img)
                out_img = base_img.copy()

                x, y = coordinates[0]
                x = min(x, out_img.shape[1] - overlay_w - 2)
                y = min(y, out_img.shape[0] - overlay_h - 2)

                color = np.random.randint(0, 80, (1, 1, 3), dtype='uint8')
                overlay_color = np.zeros_like(overlay_image[:, :, :3])
                overlay_color[:] = color

                if overlay_image.shape[2] == 4:
                    alpha = overlay_image[:, :, 3] / 255.0
                    for c in range(3):
                        out_img[y:y+overlay_h, x:x+overlay_w, c] = (
                            out_img[y:y+overlay_h, x:x+overlay_w, c] * (1 - alpha)
                            + overlay_color[:, :, c] * alpha
                        )

                filename = f"{folder_base_name}_{image_counter}.jpg"
                save_path = os.path.join(folder_path, filename)

                cv2.imwrite(save_path, out_img)

                # ✍️ WRITE CSV ROW
                base_url = "https://watermark.myofferday.online/images"
                image_name = f"{folder_base_name}_{image_counter}"
                image_url = f"{base_url}/{folder_base_name}/{filename}"

                writer.writerow([image_name, image_url])

                image_counter += 1