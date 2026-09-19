# JamuyWasi — Backend API (FastAPI)

API REST asíncrona multicliente para un marketplace SaaS de catálogos digitales con checkout directo a WhatsApp. Gestiona autenticación por roles (comerciantes y superadmin), tiendas, productos, pedidos, banners promocionales y almacenamiento de imágenes en MinIO.

---

## Stack Tecnológico

| Capa | Tecnología |
|------|------------|
| Framework | **FastAPI 0.141** (Uvicorn ASGI) |
| Python | 3.11+ |
| ORM | **SQLAlchemy 2.0** (asyncio) + **aiomysql** |
| Base de datos | **MySQL 8** (`atalaya_store`) |
| Autenticación | JWT (PyJWT) + PIN de 6 dígitos con validación anti-fuerza-bruta |
| Almacenamiento de objetos | **MinIO** (compatible S3) |
| Serialización | **Pydantic v2** / `pydantic-settings` |
| Caché | TTL en memoria (SimpleTTLCache) para listados públicos |
| Testing | pytest + pytest-asyncio |

---

## Requisitos

- Python 3.11 o superior
- MySQL 8.x (o MariaDB 10.6+) con base `atalaya_store` creada
- MinIO Server 2024+ (instancia S3-compatible)
- (Recomendado) `uv` o `pip` + `venv` para gestión de entornos

---

## Instalación y puesta en marcha

### 1. Crear entorno virtual y activar

```bash
cd backend_as
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac
```

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3. Configurar variables de entorno

Editar el archivo `.env` en la raíz de `backend_as`:

```env
# Conexión MySQL (driver async aiomysql)
DATABASE_URL=mysql+aiomysql://admin:yourpass@127.0.0.1:3306/atalaya_store

# MinIO Storage
MINIO_ENDPOINT=127.0.0.1:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin-secret
MINIO_BUCKET=atalaya-store
MINIO_SECURE=false

# Seguridad JWT (cambiar en producción!)
JWT_SECRET=super-secret-atalaya-store-jwt-key-2026-very-secure
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=10080

# CORS (acepta lista separada por comas o "*")
CORS_ORIGINS=*
```

### 4. Inicializar datos de ejemplo (seed)

Crea tablas automáticamente, crea un SuperAdmin, carga 3 tiendas demo, 4 productos destacados y 2 banners iniciales.

```bash
python -m app.seed.initial_seed
```

Credenciales por defecto del seed:

| Rol       | Email                        | Contraseña / PIN |
|-----------|------------------------------|------------------|
| SuperAdmin| `admin@jamuywasi.com`     | `admin123`       |
| Merchant (Aura) | `contacto@aura-store.com` | `tienda123` |
| Merchant (Origen Café) | `contacto@origen-cafe.com` | `tienda123` |
| Merchant (Urban Streetwear) | `contacto@urban-streetwear.com` | `tienda123` |

### 5. Levantar el servidor en modo desarrollo

```bash
uvicorn app.main:app --reload --port 8000
```

- API Base: `http://127.0.0.1:8000/api`
- Swagger (interactivo): `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- Health check: `http://127.0.0.1:8000/api/health`

### 6. Script de arranque producción (Windows)

```powershell
.\run_prod.ps1
```

---

## Arquitectura de la aplicación

```
backend_as/
├── app/
│   ├── core/             # Config, DB, seguridad, dependencias, cache, MinIO
│   │   ├── config.py          # Settings (Pydantic v2) y carga del .env
│   │   ├── database.py        # Engine async MySQL / AsyncSessionLocal
│   │   ├── deps.py            # Inyecciones: current_user / superadmin / required
│   │   ├── security.py        # JWT create/decode, hash/verify de PIN
│   │   ├── cache.py           # SimpleTTLCache (30s por defecto)
│   │   └── minio_client.py    # MinIOStorageService (bucket auto-create y policy public-read)
│   ├── models/           # Modelos SQLAlchemy
│   │   └── all_models.py      # User, Store, Product, Order, PromotionalBanner
│   ├── schemas/          # Pydantic schemas I/O
│   │   └── all_schemas.py
│   ├── routers/          # Rutas agrupadas por dominio
│   │   ├── auth.py            # Registro, login, perfil, admin usuarios
│   │   ├── stores.py          # CRUD tiendas + listado público con caché
│   │   ├── products.py        # Catálogo con filtros, ordenamiento, tracking visitas
│   │   ├── orders.py          # Pedidos + actualización de estado
│   │   ├── banners.py         # Carrusel banners (público) + gestión (admin)
│   │   └── uploads.py         # Subida de imágenes al bucket MinIO
│   ├── seed/             # Datos iniciales demo
│   │   ├── initial_seed.py
│   │   └── seed_10_stores.py
│   └── main.py           # Lifespan, CORS, registro de routers
├── tests/
│   └── test_api.py
├── .env
├── requirements.txt
├── run_prod.ps1
└── README.md
```

---

## Modelo de datos (Entidades principales)

### `User`
- Roles: `merchant` | `superadmin`
- Estados: `pending_approval` | `active` | `suspended`
- Un merchant se asocia a un único `store_id`. Un superadmin `store_id = NULL`.
- Suscripción: `starter` (gratis) | `pro` | `business`
- Autentica por email O DNI + PIN/Password de 6 dígitos (con validación anti-patrones débiles).

### `Store`
- Tiene `slug` único para URLs amigables: `dominio.pe/mi-tienda`
- Configuración de delivery (delivery_fee, free_delivery_threshold, allow_pickup)
- Configuración visual: `theme_color`, `logo`, `banner`, `socials` JSON
- Plantilla de mensaje WhatsApp personalizable
- Solo se muestra públicamente si `is_active = True` y su usuario no está pendiente/suspendido.

### `Product`
- Visibilidad: solo de tiendas activas. Relacionado con `store_id`.
- Búsqueda FULLTEXT-like por nombre, descripción, categoría (case-insensitive).
- Ordenamiento: `views` (visitas), `price_asc`, `price_desc`, `recent`.
- Filtros: categoría, rango de precios, store_ids, `only_in_stock`, `only_on_sale`.
- Campo `variants` JSON (ej: Tallas, Colores).
- Tracking de visitas atómico vía SQL `views_count = views_count + 1`.

### `Order`
- Estados: `pending_whatsapp` → `confirmed` → `preparing` → `delivered` | `cancelled`.
- `items` almacenados como JSON con snapshot del producto (precio, nombre, variante, subtotal).
- Persistencia automática al confirmar checkout por WhatsApp.

### `PromotionalBanner`
- CRUD exclusivo SuperAdmin. Lista pública solo `is_active=True` ordenada por `order`.
- Puede enlazarse a un `product_id` o `store_id` para deep-link.
- Gradiente temático: `emerald | amber | indigo | rose | purple | dark`.

---

## Endpoints Principales

### 🔐 Autenticación (prefijo `/api/auth`)
| Método | Ruta | Acceso | Descripción |
|--------|------|--------|-------------|
| POST | `/register` | Público | Crea merchant + tienda (estado `pending_approval` por defecto, requiere aprobación de superadmin). |
| POST | `/login` | Público | Login por email **o** DNI + PIN. Retorna JWT. |
| GET  | `/me` | Autenticado | Perfil del usuario actual. |
| PUT  | `/profile` | Autenticado | Actualiza datos personales + cambio de PIN (con verificación de actual). |
| GET  | `/users` | SuperAdmin | Lista de todos los usuarios (pendientes, activos, suspendidos). |
| PUT  | `/users/{id}` | SuperAdmin | Edición completa: role, store_id, status, plan, PIN reseteado. |
| PUT  | `/users/{id}/status` | SuperAdmin | Cambio rápido de estado (aprobación/suspensión → activa/desactiva la tienda asociada). |
| PUT  | `/users/{id}/role` | SuperAdmin | Promoción a superadmin o reversión a merchant. |
| DELETE | `/users/{id}` | SuperAdmin | Elimina usuario. |

### 🏪 Tiendas (prefijo `/api/stores`)
| Método | Ruta | Acceso | Descripción |
|--------|------|--------|-------------|
| GET | `?include_all=true\|false` | Público / SuperAdmin | Lista de tiendas activas (público) o todas (superadmin con include_all). Uso de caché 30s. |
| GET | `/{slug_or_id}` | Público | Detalle de tienda (fallo 404 si está inactiva y no eres admin). |
| PUT | `/{store_id}` | Dueño o SuperAdmin | Actualiza perfil de tienda (logo, banner, delivery, WhatsApp, horarios, etc.). |
| DELETE | `/{store_id}` | SuperAdmin | Elimina tienda + productos + pedidos asociados (CASCADE). |

### 🛍️ Productos (prefijo `/api/products`)
| Método | Ruta | Acceso | Descripción |
|--------|------|--------|-------------|
| GET | `/` | Público | Catálogo con filtros: `search`, `store_ids[]`, `category`, `min_price`, `max_price`, `only_in_stock`, `only_on_sale`, `sort_by`, `limit`, `offset`. Caché en queries default. |
| GET | `/{product_id}` | Público | Detalle de producto. |
| POST | `/{product_id}/visit` | Público | Incremento atómico del contador de vistas. |
| POST | `/` | Merchant (propio store) o SuperAdmin | Crea producto. |
| PUT | `/{product_id}` | Dueño o SuperAdmin | Actualiza producto. |
| DELETE | `/{product_id}` | Dueño o SuperAdmin | Elimina producto. |

### 📦 Pedidos (prefijo `/api/orders`)
| Método | Ruta | Acceso | Descripción |
|--------|------|--------|-------------|
| POST | `/` | Público | Crea pedido desde checkout WhatsApp (sin auth). |
| GET | `/store/{store_id}` | Dueño o SuperAdmin | Historial de pedidos de una tienda. |
| PATCH | `/{order_id}/status` | Dueño o SuperAdmin | Actualiza estado del pedido. |

### 🎞️ Banners (prefijo `/api/banners`)
| Método | Ruta | Acceso | Descripción |
|--------|------|--------|-------------|
| GET | `/` | Público | Banners activos ordenados para carrusel (caché 60s). |
| GET | `/all` | SuperAdmin | Todos los banners (incluye inactivos). |
| POST | `/` | SuperAdmin | Crea banner. |
| PUT | `/{banner_id}` | SuperAdmin | Edita banner. |
| DELETE | `/{banner_id}` | SuperAdmin | Elimina banner. |

### 📤 Uploads (prefijo `/api/uploads`)
| Método | Ruta | Acceso | Descripción |
|--------|------|--------|-------------|
| POST | `/image?folder=products\|logos\|banners` | Público | Sube imagen a MinIO (máx 10MB, JPG/PNG/WEBP/GIF/SVG). Retorna URL pública directa. |

---

## Seguridad y buenas prácticas

1. **JWT + PIN de 6 dígitos**: Se valida que el PIN no sea secuencial, no tenga dígitos repetidos, no coincida con el DNI ni con los últimos 6 dígitos del teléfono.
2. **Hash de credenciales**: SHA-256 con salt derivado de `JWT_SECRET[:16]` (hashing determinista para validación rápida).
3. **RBAC estricto**: Endpoints sensibles chequean `get_required_user` y `get_superadmin_user`.
4. **Filtrado de tiendas públicas**: Listados excluyen automáticamente tiendas cuyo merchant esté `pending_approval` o `suspended`.
5. **CORS configurable** por variable de entorno (`CORS_ORIGINS`).
6. **Inyección SQL mitigada**: Todo el acceso a datos vía SQLAlchemy ORM con sentencias parametrizadas.
7. **MinIO bucket policy public-read**: Solo `GetObject` anónimo; escritura requiere credenciales del backend.

---

## Pruebas

```bash
pytest tests/test_api.py -v
```

---

## Troubleshooting comunes

- **`ValidationError: DATABASE_URL Field required`**: Asegúrate de que el `.env` **no tenga BOM UTF-8** (guarda como UTF-8 normal, no UTF-8 with BOM) y la sintaxis `SettingsConfigDict` es de Pydantic v2 (la versión 1 usaba `class Config`).
- **Error de conexión MySQL**: Verifica que `DATABASE_URL` use el driver `mysql+aiomysql://` (no `mysql+pymysql`).
- **MinIO timeout**: Comprueba `MINIO_SECURE=false` si tu instancia MinIO es HTTP sin certificado, y que el puerto 9000 está accesible.
- **Uvicorn no encuentra el módulo**: Ejecuta siempre con working directory en `backend_as` y usando el Python del venv: `python -m uvicorn app.main:app` en lugar de `uvicorn` directo del PATH global.
