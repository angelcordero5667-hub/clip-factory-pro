import os
import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

logger = logging.getLogger("ThumbnailDesigner")

INTERNAL_GALLERY_DIR = Path("data/gallery")
DESKTOP_GALLERY_DIR = Path(r"C:\Users\Angel\Desktop\Galeria_Artistas")
MANIFEST_PATH = INTERNAL_GALLERY_DIR / "manifest.json"

INTERNAL_GALLERY_DIR.mkdir(parents=True, exist_ok=True)
DESKTOP_GALLERY_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def get_gallery_manifest() -> List[Dict[str, Any]]:
    """
    Devuelve la lista unificada de artistas y temas:
    Escanea la carpeta de Escritorio (C:\\Users\\Angel\\Desktop\\Galeria_Artistas)
    y la carpeta interna data/gallery/ combinando metadatos.
    """
    items_map: Dict[str, Dict[str, Any]] = {}

    # 1. Cargar manifest interno si existe
    if MANIFEST_PATH.exists():
        try:
            for item in json.loads(MANIFEST_PATH.read_text(encoding="utf-8")):
                items_map[item["id"]] = item
        except Exception as e:
            logger.debug(f"Error cargando manifest: {e}")

    # 2. Escanear carpeta de Escritorio para nuevos artistas agregados por el usuario
    if DESKTOP_GALLERY_DIR.exists():
        for file in DESKTOP_GALLERY_DIR.iterdir():
            if file.is_file() and file.suffix.lower() in IMAGE_EXTENSIONS:
                stem = file.stem
                item_id = re.sub(r"[^\w\-]", "_", stem.lower())
                name = stem.replace("_", " ").strip()
                
                # Detectar categoría según el nombre
                name_l = name.lower()
                if any(k in name_l for k in ["dinero", "millon", "alerta", "censura", "fuego", "bomba"]):
                    category = "tema"
                elif any(k in name_l for k in ["alofoke", "podcast", "show", "radio", "tv"]):
                    category = "medio"
                else:
                    category = "artista"
                    
                tags = [t.lower() for t in re.split(r"[\s_]+", name) if len(t) > 2]
                if item_id not in tags:
                    tags.append(item_id)
                    
                items_map[item_id] = {
                    "id": item_id,
                    "name": name,
                    "category": category,
                    "filename": file.name,
                    "source": "desktop",
                    "tags": tags,
                    "badge": f"🔥 {name.upper()}"
                }

    # 3. Escanear data/gallery interno para archivos no registrados
    if INTERNAL_GALLERY_DIR.exists():
        for file in INTERNAL_GALLERY_DIR.iterdir():
            if file.is_file() and file.suffix.lower() in IMAGE_EXTENSIONS:
                stem = file.stem
                item_id = re.sub(r"[^\w\-]", "_", stem.lower())
                if item_id not in items_map:
                    name = stem.replace("_", " ").strip()
                    items_map[item_id] = {
                        "id": item_id,
                        "name": name,
                        "category": "artista",
                        "filename": file.name,
                        "source": "internal",
                        "tags": [t.lower() for t in re.split(r"[\s_]+", name) if len(t) > 2],
                        "badge": f"🔥 {name.upper()}"
                    }

    return list(items_map.values())


def detect_mentioned_artists(transcript_text: str) -> List[Dict[str, Any]]:
    """Detecta qué artistas o temas de la galería son mencionados en la transcripción."""
    if not transcript_text:
        return []
    text_lower = transcript_text.lower()
    items = get_gallery_manifest()
    matched = []
    
    for item in items:
        tags = item.get("tags", [])
        for tag in tags:
            # Coincidencia con palabras mayores a 2 letras
            if len(tag) > 2 and re.search(rf"\b{re.escape(tag)}\b", text_lower):
                matched.append(item)
                break
    return matched


def resolve_asset_path(filename: str) -> Optional[Path]:
    """Busca la imagen en la carpeta del Escritorio primero, luego en data/gallery."""
    if not filename:
        return None
    d_path = DESKTOP_GALLERY_DIR / filename
    if d_path.exists():
        return d_path
    i_path = INTERNAL_GALLERY_DIR / filename
    if i_path.exists():
        return i_path
    return None


def create_viral_composite_thumbnail(
    base_frame_path: Path,
    output_path: Path,
    main_title: str,
    subtitle: str = "MOMENTO VIRAL COMPLETO 🔥",
    gallery_asset_filename: Optional[str] = None,
    top_badge: Optional[str] = None,
    channel_name: str = "🔥 BOCHINCHE VIRAL RD | EXCLUSIVA 🔥"
) -> Path:
    """
    Crea una miniatura 9:16 de altísimo CTR con composición dual (orador + artista/tema invitado)
    o composición de impacto individual con recorte y sticker fluorescentes.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGBA", (1080, 1920), (12, 12, 18, 255))
    
    # 1. Base frame (Kreizy K u orador)
    if base_frame_path.exists():
        try:
            base_img = Image.open(base_frame_path).convert("RGBA")
        except Exception:
            base_img = Image.new("RGBA", (540, 960), (30, 30, 40, 255))
    else:
        base_img = Image.new("RGBA", (540, 960), (30, 30, 40, 255))
        
    base_crop = base_img.resize((1080, 1920), Image.Resampling.LANCZOS)
    speaker_section = base_crop.crop((0, 150, 1080, 1150))
    
    # Contraste y saturación para llamar la atención en pantallas móviles
    enh_c = ImageEnhance.Contrast(speaker_section)
    speaker_section = enh_c.enhance(1.22)
    enh_col = ImageEnhance.Color(speaker_section)
    speaker_section = enh_col.enhance(1.25)
    
    canvas.paste(speaker_section, (0, 80))
    
    # Gradientes de oscurecimiento superior e inferior para legibilidad del texto
    grad = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(grad)
    for y in range(220):
        alpha = int(240 * (1 - y / 220))
        g_draw.line([(0, y), (1080, y)], fill=(10, 10, 15, alpha))
    for y in range(900, 1150):
        alpha = int(255 * (1 - abs(y - 1025) / 125))
        g_draw.line([(0, y), (1080, y)], fill=(10, 10, 15, alpha))
    for y in range(1450, 1920):
        alpha = int(255 * ((y - 1450) / 470))
        g_draw.line([(0, y), (1080, y)], fill=(10, 10, 15, alpha))
        
    canvas = Image.alpha_composite(canvas, grad)
    draw = ImageDraw.Draw(canvas)
    
    # 2. Artista o Recurso de la galería
    asset_file = resolve_asset_path(gallery_asset_filename) if gallery_asset_filename else None
    
    if asset_file:
        try:
            asset_img = Image.open(asset_file).convert("RGBA")
            aw, ah = asset_img.size
            side = min(aw, ah)
            left = (aw - side) // 2
            top = (ah - side) // 2
            asset_cropped = asset_img.crop((left, top, left + side, top + side))
            asset_box = asset_cropped.resize((720, 720), Image.Resampling.LANCZOS)
            
            # Borde brillante neón (Cutout Glow)
            border_canvas = Image.new("RGBA", (760, 760), (0, 0, 0, 0))
            b_draw = ImageDraw.Draw(border_canvas)
            b_draw.rounded_rectangle([0, 0, 760, 760], radius=48, fill=(255, 30, 100, 255))
            b_draw.rounded_rectangle([6, 6, 754, 754], radius=44, fill=(255, 220, 0, 255))
            b_draw.rounded_rectangle([14, 14, 746, 746], radius=40, fill=(0, 0, 0, 255))
            
            mask = Image.new("L", (720, 720), 0)
            m_draw = ImageDraw.Draw(mask)
            m_draw.rounded_rectangle([0, 0, 720, 720], radius=40, fill=255)
            
            border_canvas.paste(asset_box, (20, 20), mask)
            canvas.paste(border_canvas, (160, 780), border_canvas)
        except Exception as e:
            logger.warning(f"No se pudo cargar asset {gallery_asset_filename}: {e}")
    else:
        # Modo Solo: Si no hay artista invitado, agregar un badge de shock central
        draw.rounded_rectangle([420, 850, 660, 1090], radius=120, fill=(225, 29, 72, 230), outline=(255, 230, 0, 255), width=6)
        try:
            f_big_emo = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 100)
            draw.text((485, 915), "😱", font=f_big_emo, fill=(255, 255, 255))
        except Exception:
            pass

    # Fuentes
    font_bold_path = "C:/Windows/Fonts/arialbd.ttf"
    font_black_path = "C:/Windows/Fonts/impact.ttf"
    try:
        font_brand = ImageFont.truetype(font_bold_path, 38)
        font_vs = ImageFont.truetype(font_black_path, 58)
        font_title1 = ImageFont.truetype(font_black_path, 88)
        font_title2 = ImageFont.truetype(font_black_path, 80)
        font_sub = ImageFont.truetype(font_bold_path, 44)
    except:
        font_brand = ImageFont.load_default()
        font_vs = ImageFont.load_default()
        font_title1 = ImageFont.load_default()
        font_title2 = ImageFont.load_default()
        font_sub = ImageFont.load_default()
        
    # 3. Encabezado de Marca (Top pill)
    bb = font_brand.getbbox(channel_name)
    tw = bb[2] - bb[0]
    th = bb[3] - bb[1]
    bx = (1080 - tw) // 2
    draw.rounded_rectangle([bx - 24, 38, bx + tw + 24, 38 + th + 18], radius=16, fill=(225, 29, 72, 255), outline=(255, 255, 255, 220), width=2)
    draw.text((bx, 46), channel_name, font=font_brand, fill=(255, 255, 255, 255))
    
    # 4. Conector Central (Rayo / Conflicto)
    badge = top_badge or ("⚡ ¿QUÉ DIJO REALMENTE? ⚡" if asset_file else "🚨 REACCIÓN EN VIVO 🚨")
    vbb = font_vs.getbbox(badge)
    vw = vbb[2] - vbb[0]
    vh = vbb[3] - vbb[1]
    vx = (1080 - vw) // 2
    draw.rounded_rectangle([vx - 26, 715, vx + vw + 26, 715 + vh + 22], radius=18, fill=(255, 220, 0, 255), outline=(0, 0, 0, 255), width=5)
    draw.text((vx, 722), badge, font=font_vs, fill=(10, 10, 10, 255))
    
    # 5. Titular Gigante en Cajas Sticker (Inferior)
    words = main_title.split(" ")
    mid = len(words) // 2 if len(words) > 3 else len(words)
    line1 = " ".join(words[:mid]) if mid < len(words) else main_title
    line2 = " ".join(words[mid:]) if mid < len(words) else ""
    
    l1_bb = font_title1.getbbox(line1)
    l1w = l1_bb[2] - l1_bb[0]
    l1h = l1_bb[3] - l1_bb[1]
    l1x = (1080 - l1w) // 2
    l1y = 1550
    
    draw.rounded_rectangle([l1x - 24, l1y - 8, l1x + l1w + 24, l1y + l1h + 16], radius=16, fill=(0, 0, 0, 240), outline=(255, 215, 0, 255), width=4)
    draw.text((l1x + 4, l1y + 4), line1, font=font_title1, fill=(0, 0, 0, 255))
    draw.text((l1x, l1y), line1, font=font_title1, fill=(255, 235, 0, 255))
    
    if line2:
        l2_bb = font_title2.getbbox(line2)
        l2w = l2_bb[2] - l2_bb[0]
        l2h = l2_bb[3] - l2_bb[1]
        l2x = (1080 - l2w) // 2
        l2y = l1y + l1h + 34
        draw.rounded_rectangle([l2x - 20, l2y - 6, l2x + l2w + 20, l2y + l2h + 14], radius=14, fill=(225, 29, 72, 235), outline=(255, 255, 255, 255), width=3)
        draw.text((l2x + 3, l2y + 3), line2, font=font_title2, fill=(0, 0, 0, 255))
        draw.text((l2x, l2y), line2, font=font_title2, fill=(255, 255, 255, 255))
        bottom_y = l2y + l2h + 28
    else:
        bottom_y = l1y + l1h + 36
        
    # Subtítulo cian al pie
    sbb = font_sub.getbbox(subtitle)
    sw = sbb[2] - sbb[0]
    sx = (1080 - sw) // 2
    draw.text((sx + 2, bottom_y + 2), subtitle, font=font_sub, fill=(0, 0, 0, 255))
    draw.text((sx, bottom_y), subtitle, font=font_sub, fill=(56, 189, 248, 255))
    
    out_rgb = canvas.convert("RGB")
    out_rgb.save(output_path, "JPEG", quality=95)
    logger.info(f"Miniatura viral compuesta exitosamente en: {output_path}")
    return output_path


def auto_generate_viral_thumbnail_for_candidate(
    clip_path: Path,
    title: str,
    transcript_text: str = "",
    hook_text: str = ""
) -> Path:
    """
    Automatiza al 100% la creación de la miniatura 9:16 cuando se genera un clip.
    Detecta menciones de artistas de la carpeta de artistas y compone la miniatura completa.
    """
    thumb_path = clip_path.with_suffix(".jpg")
    search_text = f"{title} {hook_text} {transcript_text}".lower()
    
    matches = detect_mentioned_artists(search_text)
    asset_file = None
    badge = None
    if matches:
        top_match = matches[0]
        asset_file = top_match.get("filename")
        badge = top_match.get("badge")
        
    main_title = hook_text.upper() if hook_text else title.upper()
    if len(main_title) > 36:
        main_title = main_title[:36].rsplit(" ", 1)[0] + "..."
        
    return create_viral_composite_thumbnail(
        base_frame_path=thumb_path,
        output_path=thumb_path,
        main_title=main_title,
        subtitle="MOMENTO VIRAL COMPLETO 🔥",
        gallery_asset_filename=asset_file,
        top_badge=badge
    )
