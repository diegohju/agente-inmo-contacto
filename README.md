# 🏠 Agente Inmobiliario — Portal Inmobiliario Chile

Agente autónomo que **raspa Portal Inmobiliario** cada día a las 8 AM, extrae
datos de inmobiliarias (nombre, email, región, cantidad de avisos) y los guarda
automáticamente en **Supabase**.

## Arquitectura

```
GitHub Actions (cron diario)
       │
       ▼
Python + Selenium  ←→  Portal Inmobiliario Chile
       │                    Google Search (email lookup)
       ▼
  Supabase DB
  ├── tabla: inmobiliarias
  └── tabla: ejecuciones
```

## Estructura de archivos

```
AGENTE INMO CONTACTO/
├── .github/
│   └── workflows/
│       └── scraper.yml          ← cron + CI/CD
├── scraper/
│   ├── scraper_portal_inmobiliario.py   ← agente principal
│   └── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## 🚀 Setup en 5 pasos

### 1. Crear repositorio en GitHub

```bash
cd "AGENTE INMO CONTACTO"
git init
git add .
git commit -m "feat: agente inmobiliario inicial"
```

Crea un repo en [github.com/new](https://github.com/new) y sube el código:

```bash
git remote add origin https://github.com/TU_USUARIO/agente-inmo-contacto.git
git branch -M main
git push -u origin main
```

---

### 2. Obtener la Service Role Key de Supabase

1. Ve a [supabase.com/dashboard](https://supabase.com/dashboard)
2. Selecciona el proyecto **"Agente Inmo Contacto"**
3. Ve a **Settings → API**
4. Copia la key **`service_role`** (la secreta, no la `anon`)

> ⚠️ **NUNCA** subas esta key al repositorio. Solo va en GitHub Secrets.

---

### 3. Configurar GitHub Secrets

En tu repo de GitHub → **Settings → Secrets and variables → Actions → New secret**:

| Nombre | Valor |
|--------|-------|
| `SUPABASE_URL` | `https://jqhzswjegqytyanpfngy.supabase.co` |
| `SUPABASE_SERVICE_KEY` | `tu_service_role_key_de_supabase` |

---

### 4. El agente corre automáticamente

El workflow está configurado para correr **todos los días a las 8:00 AM hora Chile** (11:00 UTC).

Para ejecutarlo **manualmente** ahora mismo:
1. Ve a tu repo en GitHub → pestaña **Actions**
2. Haz clic en **"🏠 Agente Inmobiliario — Scraper Diario"**
3. Clic en **"Run workflow"** → puedes elegir número de páginas

---

### 5. Ver resultados en Supabase

Ve a [supabase.com/dashboard](https://supabase.com/dashboard) → **Table Editor**:

- **`inmobiliarias`** → todos los prospectos con email, región, etc.
- **`ejecuciones`** → historial de cada corrida del agente

---

## 🔧 Desarrollo local

```bash
cd scraper
cp ../.env.example .env
# Edita .env con tu SUPABASE_SERVICE_KEY real

pip install -r requirements.txt
python scraper_portal_inmobiliario.py
```

---

## ⚙️ Variables de configuración

| Variable | Default | Descripción |
|----------|---------|-------------|
| `MAX_PAGINAS` | `10` | Páginas de Portal Inmobiliario a scrapear |
| `BUSCAR_EMAILS` | `true` | Activa el email lookup vía Google |
| `DELAY_PAGINA` | `3` | Segundos entre páginas (anti-bloqueo) |

---

## 📊 Tablas en Supabase

### `inmobiliarias`
| Columna | Tipo | Descripción |
|---------|------|-------------|
| `nombre_inmobiliaria` | text | Nombre único (clave de upsert) |
| `email` | text | Email encontrado |
| `email_fuente` | text | `aviso` / `google` / `sitio_web` / `no encontrado` |
| `total_avisos` | int | Cantidad de avisos publicados |
| `regiones_presentes` | text | Regiones donde publica |
| `fecha_extraccion` | date | Última vez que se procesó |
| `contactado` | bool | Si ya le contactaste (para tu CRM) |
| `respuesta` / `notas` | text | Para tu seguimiento |

### `ejecuciones`
Historial de cada corrida: inicio, fin, estado, estadísticas.

---

## 💡 Tips

- **Captcha de Google**: Si Google bloquea, el agente continúa y marca esas empresas como `"captcha"`. No se cuelga.
- **Upsert**: Cada corrida actualiza los datos existentes (no duplica). Puedes marcar manualmente `contactado = true` y no se sobreescribirá el email.
- **Cron personalizado**: Edita la línea `cron:` en `.github/workflows/scraper.yml` para cambiar el horario.
