"""Display driver interface."""

from __future__ import annotations

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


class DisplayDriver:
    @property
    def width(self) -> int:
        raise NotImplementedError

    @property
    def height(self) -> int:
        raise NotImplementedError

    def draw_image(self, x: int, y: int, width: int, height: int, pixel_data) -> None:
        raise NotImplementedError

    def fill_screen(self, color: int) -> None:
        raise NotImplementedError

    def set_backlight(self, brightness: int) -> None:
        pass

    def cleanup(self) -> None:
        pass

    def crop_to_cover(self, img):
        """Resize image to cover the display area with center crop."""
        w, h = self.width, self.height
        orig_w, orig_h = img.size
        scale = max(w / orig_w, h / orig_h)
        new_w, new_h = int(orig_w * scale), int(orig_h * scale)
        img = img.resize((new_w, new_h))
        left = (new_w - w) // 2
        top = (new_h - h) // 2
        return img.crop((left, top, left + w, top + h))

    @staticmethod
    def image_to_rgb565(img):
        """Convert PIL RGB image to RGB565 bytes."""
        img = img.convert("RGB")
        if _HAS_NUMPY:
            arr = np.array(img)
            r = arr[:, :, 0].astype(np.uint16)
            g = arr[:, :, 1].astype(np.uint16)
            b = arr[:, :, 2].astype(np.uint16)
            rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            return rgb565.astype(">u2").tobytes()
        else:
            w, h = img.size
            raw = img.tobytes()
            pixel_data = bytearray(w * h * 2)
            for i in range(w * h):
                r, g, b = raw[i * 3], raw[i * 3 + 1], raw[i * 3 + 2]
                rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                pixel_data[i * 2] = (rgb565 >> 8) & 0xFF
                pixel_data[i * 2 + 1] = rgb565 & 0xFF
            return bytes(pixel_data)
