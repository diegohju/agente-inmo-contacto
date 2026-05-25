# scraper_portal_inmobiliario.py
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
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from supabase import create_client, Client

# ── CONFIGURACIÓN ──────────────────────────────────────────
MAX_PAGINAS     = int(os.getenv("MAX_PAGINAS", "10"))
DELAY_PAGINA    = int(os.getenv("DELAY_PAGINA", "3"))
BUSCAR_EMAILS   = os.getenv("BUSCAR_EMAILS", "true").lower() == "true"
PRECIO_MINIMO   = int(os.getenv("PRECIO_MINIMO", "300000000")) # 300 Millones CLP
# URL base filtrando propiedades en venta sobre 8000 UF (~300M CLP) para optimizar la búsqueda
BASE_URL        = "https://www.portalinmobiliario.com/venta/_Desde_8000-UF"
SUPABASE_URL    = os.getenv("SUPABASE_URL")
SUPABASE_KEY    = os.getenv("SUPABASE_SERVICE_KEY")   # service_role key (en GitHub Secrets)
# ──────────────────────────────────────────────────────────

if not SUPABASE_URL or not SUPABASE_KEY:
    print("\n❌ ERROR: Faltan las variables de entorno de Supabase.")
    print("Asegúrate de configurar 'SUPABASE_URL' y 'SUPABASE_SERVICE_KEY' en los Secrets de GitHub.")
    print(f"SUPABASE_URL detectada: {'Sí' if SUPABASE_URL else 'No'}")
    print(f"SUPABASE_SERVICE_KEY detectada: {'Sí' if SUPABASE_KEY else 'No'}\n")
    exit(9)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ── DRIVER ────────────────────────────────────────────────
def init_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    try:
        # En CI (GitHub Actions) Chrome está instalado globalmente
        options.binary_location = "/usr/bin/google-chrome"
        service = Service("/usr/bin/chromedriver")
        return webdriver.Chrome(service=service, options=options)
    except Exception:
        # Fallback: webdriver-manager (local)
        return webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), options=options
        )


# ── UTILIDADES DE EMAIL Y PRECIO ──────────────────────────
PATRON_EMAIL = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
IGNORAR_EMAIL = ["google", "youtube", "gmail.com", "example", "test",
                 "portalinmobiliario", "yapo", "toctoc"]


def extraer_email(texto: str) -> str | None:
    """Extrae el primer email válido de un texto."""
    emails = re.findall(PATRON_EMAIL, texto)
    for e in emails:
        if not any(x in e.lower() for x in IGNORAR_EMAIL):
            return e.lower()
    return None


def extraer_precio_clp(soup) -> int:
    """Extrae el precio del aviso y lo convierte a CLP si está en UF."""
    price_elem = soup.select_one('.ui-pdp-price__part .andes-money-amount__fraction')
    currency_elem = soup.select_one('.ui-pdp-price__part .andes-money-amount__currency-symbol')
    
    if not price_elem or not currency_elem:
        price_elem = soup.select_one('[class*="price"] [class*="fraction"]')
        currency_elem = soup.select_one('[class*="price"] [class*="symbol"]')
        
    if price_elem and currency_elem:
        try:
            val_str = price_elem.get_text(strip=True).replace('.', '').replace(',', '')
            val = int(val_str)
            currency = currency_elem.get_text(strip=True)
            if 'UF' in currency.upper():
                # Asumimos UF referencial de $38.000 CLP para la validación
                return val * 38000
            elif '$' in currency:
                return val
        except Exception:
            pass
    return 0


def normalizar_nombre(nombre: str) -> str:
    return re.sub(r"\s+", " ", nombre.strip()).title()


# ── EMAIL LOOKUP ──────────────────────────────────────────
def email_lookup(driver: webdriver.Chrome, nombre_empresa: str) -> tuple[str, str]:
    """
    Busca el email de una inmobiliaria en 2 pasos:
    1. Google Search → snippets de resultados
    2. Sitio web de la empresa → páginas /contacto
    Retorna (email, fuente) donde fuente ∈ {'google','sitio_web','no encontrado','captcha'}
    """
    time.sleep(random.uniform(2.5, 4.5))

    query = f"{nombre_empresa} inmobiliaria Chile email contacto"
    url_google = f"https://www.google.com/search?q={urllib.parse.quote(query)}"

    try:
        driver.get(url_google)
        time.sleep(random.uniform(2, 3))
        soup = BeautifulSoup(driver.page_source, "html.parser")

        # Detectar captcha
        if ("captcha" in driver.current_url.lower()
                or "unusual traffic" in soup.get_text().lower()):
            print(f"  ⚠️  Google captcha → {nombre_empresa}")
            return "no encontrado", "captcha"

        # Paso 1: email en snippets de Google
        email = extraer_email(soup.get_text())
        if email:
            return email, "google"

        # Paso 2: ir al sitio web de la empresa
        dominios_ignorar = ["google", "portalinmobiliario", "yapo", "toctoc",
                            "facebook", "instagram", "linkedin", "twitter"]
        sitio = None
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if href.startswith("/url?q="):
                url_real = urllib.parse.unquote(href.split("/url?q=")[1].split("&")[0])
                if (url_real.startswith("http")
                        and not any(d in url_real.lower() for d in dominios_ignorar)):
                    sitio = url_real
                    break

        if sitio:
            for sufijo in ["/contacto", "/contactanos", "/contact", "/quienes-somos", ""]:
                try:
                    driver.get(sitio.rstrip("/") + sufijo)
                    time.sleep(random.uniform(1.5, 2.5))
                    texto = driver.find_element(By.TAG_NAME, "body").text
                    email = extraer_email(texto)
                    if email:
                        return email, "sitio_web"
                except Exception:
                    continue

    except Exception as e:
        print(f"  Lookup error ({nombre_empresa}): {e}")

    return "no encontrado", "no encontrado"


# ── SCRAPING DE AVISO INDIVIDUAL ──────────────────────────
KEYWORDS_EMPRESA = [
    "inmobiliaria", "constructora", "bienes raíces", "propiedades",
    "grupo", "s.a.", "spa", "ltda", "corp", "realty", "homes",
]


def scrape_aviso(driver: webdriver.Chrome, url: str) -> dict | None:
    """Extrae datos de un aviso. Retorna None si no cumple el precio o no es empresa."""
    try:
        driver.get(url)
        WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        soup = BeautifulSoup(driver.page_source, "html.parser")

        # ── NUEVO: Filtrar por precio ────────────────────
        precio_clp = extraer_precio_clp(soup)
        if precio_clp < PRECIO_MINIMO:
            # Si el precio es menor al configurado (300M CLP), ignoramos el aviso
            return None

        # Detectar publicador
        publicador = ""
        for sel in [
            ".advertiser-name", ".seller-name", '[class*="advertiser"]',
            '[class*="seller"]', '[class*="publisher"]', '[class*="agency"]',
        ]:
            elem = soup.select_one(sel)
            if elem:
                publicador = elem.get_text(strip=True)
                break

        if not publicador:
            return None

        # Filtrar personas físicas
        es_empresa = (
            any(k in publicador.lower() for k in KEYWORDS_EMPRESA)
            or len(publicador.split()) >= 3
        )
        if not es_empresa:
            return None

        email = extraer_email(soup.get_text())

        # Región y tipo desde breadcrumb
        region = tipo = ""
        for bc in soup.select(".breadcrumb a, [class*='breadcrumb'] a"):
            t = bc.get_text(strip=True)
            if any(x in t.lower() for x in [
                "región", "metropolitana", "valparaíso", "antofagasta",
                "biobío", "araucanía", "coquimbo", "maule", "tarapacá",
            ]):
                region = t
            if any(x in t.lower() for x in [
                "casa", "departamento", "terreno", "oficina", "local",
            ]):
                tipo = t

        return {
            "publicador": publicador,
            "email": email,
            "tipo": tipo,
            "region": region,
            "url": url,
        }
    except Exception:
        return None


# ── SUPABASE: REGISTRO DE EJECUCIÓN ──────────────────────
def registrar_inicio() -> str:
    """Crea un registro de ejecución y retorna su ID."""
    res = (
        supabase.table("ejecuciones")
        .insert({"estado": "corriendo", "inicio": datetime.utcnow().isoformat()})
        .execute()
    )
    return res.data[0]["id"]


def registrar_fin(eje_id: str, stats: dict):
    supabase.table("ejecuciones").update({
        "estado": "completado",
        "fin": datetime.utcnow().isoformat(),
        **stats,
    }).eq("id", eje_id).execute()


def registrar_error(eje_id: str, mensaje: str):
    supabase.table("ejecuciones").update({
        "estado": "error",
        "fin": datetime.utcnow().isoformat(),
        "error_mensaje": mensaje,
    }).eq("id", eje_id).execute()


def guardar_inmobiliarias(consolidado: dict):
    """Hace upsert de cada inmobiliaria en Supabase."""
    rows = []
    for nombre, data in consolidado.items():
        rows.append({
            "nombre_inmobiliaria": nombre,
            "email": data.get("email") or "no encontrado",
            "email_fuente": data.get("email_fuente") or "no encontrado",
            "total_avisos": data.get("total_avisos", 1),
            "regiones_presentes": ", ".join(data.get("regiones", set())),
            "fecha_extraccion": date.today().isoformat(),
        })

    if rows:
        supabase.table("inmobiliarias").upsert(
            rows, on_conflict="nombre_inmobiliaria"
        ).execute()
        print(f"  ✅ {len(rows)} inmobiliarias guardadas en Supabase.")


# ── MAIN ──────────────────────────────────────────────────
def main():
    print("🏠 Agente Inmobiliario — Portal Inmobiliario Chile")
    print("=" * 50)
    print(f"Páginas: {MAX_PAGINAS}  |  Email lookup: {BUSCAR_EMAILS}")
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    eje_id = registrar_inicio()
    driver = None

    try:
        driver = init_driver()
        avisos: list[dict] = []
        urls_vistas: set[str] = set()

        # ── Fase 1: Scraping de listados ────────────────────
        print(f"\n📋 FASE 1: Scraping de {MAX_PAGINAS} páginas de listados")
        for pag in range(1, MAX_PAGINAS + 1):
            print(f"\n  📄 Página {pag}/{MAX_PAGINAS}")
            driver.get(f"{BASE_URL}?pagina={pag}")
            time.sleep(DELAY_PAGINA)
            soup = BeautifulSoup(driver.page_source, "html.parser")

            links: list[str] = []
            for a in soup.find_all("a", href=True):
                h = a["href"]
                if any(x in h for x in ["/MLA", "/MLU", "/propiedades/"]):
                    url = (
                        h if h.startswith("http")
                        else f"https://www.portalinmobiliario.com{h}"
                    )
                    if url not in urls_vistas:
                        links.append(url)
                        urls_vistas.add(url)

            print(f"  → {len(links)} avisos encontrados")

            for url in links[:20]:
                r = scrape_aviso(driver, url)
                if r:
                    avisos.append(r)
                time.sleep(random.uniform(1, 2))

        print(f"\n✅ Fase 1 completa — {len(avisos)} avisos de inmobiliarias")

        # ── Fase 2: Consolidar por empresa ──────────────────
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
                }
            consolidado[nombre]["total_avisos"] += 1
            if item["region"]:
                consolidado[nombre]["regiones"].add(item["region"])
            # Si aún no tiene email, toma el del aviso actual
            if item["email"] and not consolidado[nombre]["email_fuente"]:
                consolidado[nombre]["email"] = item["email"]
                consolidado[nombre]["email_fuente"] = "aviso"

        print(f"  → {len(consolidado)} inmobiliarias únicas")

        # ── Fase 3: Email lookup ─────────────────────────────
        emails_por_lookup = 0
        if BUSCAR_EMAILS:
            sin_email = [n for n, d in consolidado.items() if not d["email_fuente"]]
            print(f"\n🔍 FASE 3: Email lookup para {len(sin_email)} inmobiliarias sin email")
            for i, nombre in enumerate(sin_email, 1):
                print(f"  [{i}/{len(sin_email)}] {nombre}...")
                email, fuente = email_lookup(driver, nombre)
                consolidado[nombre]["email"] = email
                consolidado[nombre]["email_fuente"] = fuente
                if email != "no encontrado":
                    print(f"  ✓ {email} ({fuente})")
                    emails_por_lookup += 1

        # ── Fase 4: Guardar en Supabase ──────────────────────
        print("\n💾 FASE 4: Guardando en Supabase...")
        guardar_inmobiliarias(consolidado)

        # Estadísticas finales
        total = len(consolidado)
        con_email = sum(
            1 for d in consolidado.values()
            if d.get("email") not in (None, "no encontrado")
        )
        stats = {
            "paginas_scrapeadas": MAX_PAGINAS,
            "avisos_procesados": len(avisos),
            "inmobiliarias_encontradas": total,
            "emails_encontrados": con_email,
            "emails_por_lookup": emails_por_lookup,
        }
        registrar_fin(eje_id, stats)

        print("\n" + "=" * 50)
        print("🎉 ¡AGENTE COMPLETADO!")
        print(f"📊 Inmobiliarias únicas : {total}")
        print(f"📧 Con email            : {con_email} ({round(con_email/total*100) if total else 0}%)")
        print(f"🔍 Encontrados lookup   : {emails_por_lookup}")
        print("=" * 50)

    except Exception as e:
        print(f"\n❌ Error crítico: {e}")
        if eje_id:
            registrar_error(eje_id, str(e))
        raise
    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
