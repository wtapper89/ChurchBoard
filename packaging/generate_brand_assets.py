from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "packaging" / "assets"
STATIC = ROOT / "app" / "static"
ICON_SOURCE = ASSETS / "churchboard-icon-source.png"
LOGO_SOURCE = ASSETS / "churchboard-logo-source.png"


def transparent_corners(path: Path) -> Image.Image:
    """Remove only the connected near-black canvas surrounding the supplied art."""
    image = Image.open(path).convert("RGBA")
    marker = (255, 0, 255, 255)
    working = image.copy()
    for corner in ((0, 0), (working.width - 1, 0), (0, working.height - 1), (working.width - 1, working.height - 1)):
        ImageDraw.floodfill(working, corner, marker, thresh=52)
    pixels = working.load()
    source = image.load()
    for y in range(working.height):
        for x in range(working.width):
            if pixels[x, y] == marker:
                source[x, y] = (source[x, y][0], source[x, y][1], source[x, y][2], 0)
    return image


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Helvetica.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def create_dmg_background(icon: Image.Image, logo: Image.Image) -> Image.Image:
    base = ImageOps.fit(icon.convert("RGB"), (900, 760), method=Image.Resampling.LANCZOS, centering=(0.5, 0.54))
    base = ImageEnhance.Brightness(base).enhance(0.72).convert("RGBA")
    base.alpha_composite(Image.new("RGBA", base.size, (255, 246, 230, 55)))
    draw = ImageDraw.Draw(base)

    draw.rounded_rectangle((32, 24, 868, 160), radius=28, fill=(255, 250, 241, 238), outline=(121, 65, 25, 120), width=2)
    logo_thumb = ImageOps.contain(logo, (116, 116), Image.Resampling.LANCZOS)
    base.alpha_composite(logo_thumb, (52, 34))
    draw.text((188, 48), "Install ChurchBoard", font=font(39, bold=True), fill=(48, 28, 18, 255))
    draw.text((190, 101), "Drag the ChurchBoard app onto Applications", font=font(22), fill=(93, 55, 31, 255))

    draw.rounded_rectangle((74, 218, 354, 476), radius=30, fill=(255, 250, 242, 212), outline=(111, 61, 27, 120), width=2)
    draw.rounded_rectangle((546, 218, 826, 476), radius=30, fill=(255, 250, 242, 212), outline=(111, 61, 27, 120), width=2)
    draw.line((388, 348, 507, 348), fill=(111, 59, 25, 255), width=18)
    draw.polygon(((507, 315), (550, 348), (507, 381)), fill=(111, 59, 25, 255))
    draw.text((398, 392), "DRAG TO INSTALL", font=font(17, bold=True), fill=(72, 38, 20, 255))
    draw.rounded_rectangle((52, 498, 848, 736), radius=20, fill=(55, 31, 18, 218), outline=(255, 247, 233, 70), width=2)
    draw.text((76, 516), "OPTIONAL: ENABLE HTTPS", font=font(16, bold=True), fill=(232, 190, 132, 255))
    draw.text((76, 551), "After installing the app, double-click", font=font(18), fill=(255, 250, 242, 255))
    draw.text((76, 579), "Enable HTTPS on the right.", font=font(18, bold=True), fill=(255, 250, 242, 255))
    draw.text((76, 630), "Creates, trusts, and configures your", font=font(15), fill=(242, 221, 198, 255))
    draw.text((76, 653), "certificate automatically.", font=font(15), fill=(242, 221, 198, 255))
    draw.text((76, 700), "The ChurchBoard icon stays in your menu bar while it runs.", font=font(14), fill=(242, 221, 198, 255))
    return base.convert("RGB")


def create_icns(icon: Image.Image, destination: Path) -> None:
    icon.save(
        destination,
        format="ICNS",
        sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)],
    )


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    STATIC.mkdir(parents=True, exist_ok=True)
    icon = transparent_corners(ICON_SOURCE)
    logo = transparent_corners(LOGO_SOURCE)

    icon_512 = icon.resize((512, 512), Image.Resampling.LANCZOS)
    logo_512 = logo.resize((512, 512), Image.Resampling.LANCZOS)
    icon_512.save(STATIC / "churchboard-icon.png", optimize=True)
    logo_512.save(STATIC / "churchboard-logo.png", optimize=True)
    icon_512.save(ASSETS / "ChurchBoard.ico", format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    create_icns(icon, ASSETS / "ChurchBoard.icns")
    create_dmg_background(icon, logo).save(ASSETS / "dmg-background.png", optimize=True)


if __name__ == "__main__":
    main()
