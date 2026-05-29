# scraper_portal_inmobiliario.py
# (Reescrito para usar economicos.cl porque Portal Inmobiliario bloquea CI)
# Agente autónomo de prospección inmobiliaria
# GitHub Actions + Supabase
#
# pip install -r requirements.txt

import os
import re
import time
import random
import urllib.parse
from datetime import datetime, date

import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client

# ── CONFIGURACIÓN ──────────────────────────────────────────
MAX_PAGINAS     = int(os.getenv("MAX_PAGINAS", "10"))
DELAY_PAGINA    = int(os.getenv("DELAY_PAGINA", "3"))
BUSCAR_EMAILS   = os.getenv("BUSCAR_EMAILS", "true").lower() == "true"
BASE_URL        = "https://www.economicos.cl/propiedades"
SUPABASE_URL    = os.getenv("SUPABASE_URL")
SUPABASE_KEY    = os.getenv("SUPABASE_SERVICE_KEY")   # service_role key (en GitHub Secrets)
# ──────────────────────────────────────────────────────────

if not SUPABASE_URL or not SUPABASE_KEY:
    print("\n❌ ERROR: Faltan las variables de entorno de Supabase.")
    exit(9)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ── UTILIDADES DE EMAIL Y PRECIO ──────────────────────────
PATRON_EMAIL = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
IGNORAR_EMAIL = ["google", "youtube", "gmail.com", "example", "test",
                 "portalinmobiliario", "yapo", "toctoc", "economicos.cl"]

KEYWORDS_EMPRESA = [
    "inmobiliaria", "constructora", "bienes raíces", "propiedades",
    "grupo", "s.a.", "spa", "ltda", "corp", "realty", "homes",
    "corretaje", "corredora", "gestión"
]

def extraer_email(texto: str) -> str | None:
    emails = re.findall(PATRON_EMAIL, texto)
    for email in emails:
        e = email.lower()
        if not any(ignorado in e for ignorado in IGNORAR_EMAIL):
            return e
    return None

def normalizar_nombre(nombre: str) -> str:
    """Limpia y normaliza el nombre de la inmobiliaria para evitar duplicados."""
    n = nombre.upper()
    n = re.sub(r'[^A-Z0-9\s]', '', n)
    n = re.sub(r'\b(LTDA|LIMITADA|SPA|SA|S\.A\.|CORREDORA DE PROPIEDADES|PROPIEDADES|INMOBILIARIA)\b', '', n)
    n = " ".join(n.split())
    if not n:
        return nombre.upper().strip()
    return n

def extraer_precio(soup: BeautifulSoup) -> tuple[int, str]:
    """Busca el precio en la página."""
    try:
        precio_elem = soup.select_one('.price, .ecn_price')
        if precio_elem:
            t = precio_elem.get_text(strip=True)
            numeros = re.sub(r'[^\d]', '', t)
            if numeros:
                return int(numeros), t
    except Exception:
        pass
    return 0, ""

# ── LOGICA PRINCIPAL ──────────────────────────────────────
def scrape_aviso(url: str) -> dict | None:
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        # Detectar publicador
        publicador = ""
        elem = soup.select_one('.cont_ecn_name_vendor')
        if elem:
            publicador = elem.get_text(strip=True)

        if not publicador or publicador.lower() in ['publicar en papel', 'subir de posición', 'dar de baja']:
            return None

        es_empresa = (
            any(k in publicador.lower() for k in KEYWORDS_EMPRESA)
            or len(publicador.split()) >= 3
        )
        if not es_empresa:
            return None

        email = extraer_email(soup.get_text())
        precio_clp, precio_texto = extraer_precio(soup)

        return {
            "publicador": publicador,
            "email": email,
            "tipo": "Propiedad",
            "region": "",
            "url": url,
            "precio_clp": precio_clp,
            "precio_texto": precio_texto,
        }
    except Exception as e:
        print(f"      [!] Excepción: {e}")
        return None

def registrar_inicio() -> str:
    res = supabase.table("ejecuciones").insert({
        "inicio": datetime.now().isoformat(),
        "estado": "en_progreso"
    }).execute()
    return res.data[0]["id"]

def registrar_fin(eje_id: str, paginas: int, avisos: int, inmos: int, emails: int, error: str = None):
    supabase.table("ejecuciones").update({
        "fin": datetime.now().isoformat(),
        "estado": "completado" if not error else "error",
        "paginas_scrapeadas": paginas,
        "avisos_procesados": avisos,
        "inmobiliarias_encontradas": inmos,
        "emails_encontrados": emails,
        "error_mensaje": error
    }).eq("id", eje_id).execute()

def main():
    print("🏠 Agente Inmobiliario — Economicos.cl (Alternativa anti-bloqueo)")
    print("=" * 50)
    print(f"Páginas: {MAX_PAGINAS}  |  Email lookup: {BUSCAR_EMAILS}")
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    eje_id = registrar_inicio()

    try:
        avisos: list[dict] = []
        urls_vistas: set[str] = set()

        print(f"\n📋 FASE 1: Scraping de {MAX_PAGINAS} páginas de listados")
        for pag in range(1, MAX_PAGINAS + 1):
            print(f"\n  📄 Página {pag}/{MAX_PAGINAS}")
            url_pagina = f"{BASE_URL}?page={pag}"
            r = requests.get(url_pagina, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(r.text, "html.parser")

            links = []
            for a in soup.select('a[href*="/propiedades/"]'):
                h = a["href"]
                url = h if h.startswith("http") else f"https://www.economicos.cl{h}"
                if url not in urls_vistas:
                    links.append(url)
                    urls_vistas.add(url)

            print(f"  → {len(links)} links encontrados")

            avisos_pagina = 0
            for url in links[:20]: # Limitar a 20 por página para no demorar mucho
                r_aviso = scrape_aviso(url)
                if r_aviso:
                    print(f"    ✓ Empresa: {r_aviso['publicador']}")
                    avisos.append(r_aviso)
                    avisos_pagina += 1
                time.sleep(random.uniform(0.5, 1.5))
            print(f"  → {avisos_pagina} avisos de empresa en esta página")

        # ── Fase 2: Consolidar ──────────────────
        print("\n📊 FASE 2: Consolidando por inmobiliaria...")
        consolidado: dict[str, dict] = {}
        for item in avisos:
            nombre = normalizar_nombre(item["publicador"])
            if nombre not in consolidado:
                consolidado[nombre] = {
                    "nombre_inmobiliaria": nombre,
                    "email": item["email"],
                    "total_avisos": 0,
                    "regiones": set(),
                    "email_fuente": "aviso" if item["email"] else None,
                    "precio_max_clp": 0,
                    "precio_texto": "",
                }
            consolidado[nombre]["total_avisos"] += 1
            if item.get("precio_clp", 0) > consolidado[nombre]["precio_max_clp"]:
                consolidado[nombre]["precio_max_clp"] = item["precio_clp"]
                consolidado[nombre]["precio_texto"] = item.get("precio_texto", "")
            if item["email"] and not consolidado[nombre]["email_fuente"]:
                consolidado[nombre]["email"] = item["email"]
                consolidado[nombre]["email_fuente"] = "aviso"

        # Guardar en base de datos
        print("\n💾 FASE 4: Guardando en Supabase...")
        filas = []
        for key, data in consolidado.items():
            filas.append({
                "nombre_inmobiliaria": data["nombre_inmobiliaria"],
                "email": data["email"],
                "ultima_actualizacion": datetime.now().isoformat(),
                "total_avisos": data["total_avisos"],
                "precio_max_clp": data["precio_max_clp"],
                "precio_texto": data["precio_texto"],
                "origen": "economicos.cl"
            })

        for row in filas:
            supabase.table("inmobiliarias").upsert(row, on_conflict="nombre_inmobiliaria").execute()

        registrar_fin(eje_id, MAX_PAGINAS, len(avisos), len(consolidado), sum(1 for f in filas if f["email"]))

        print("\n🎉 ¡AGENTE COMPLETADO!")
        print(f"📊 Inmobiliarias únicas : {len(consolidado)}")
    except Exception as e:
        registrar_fin(eje_id, 0, 0, 0, 0, str(e))
        print(f"\n❌ Error crítico: {e}")
        raise e

if __name__ == "__main__":
    main()
