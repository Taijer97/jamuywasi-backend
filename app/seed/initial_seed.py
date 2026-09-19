import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal, engine, Base
from app.core.security import hash_password
from app.models.all_models import Store, Product, User, PromotionalBanner

INITIAL_STORES = [
    {
        "id": "store_aura",
        "name": "Aura Concept Store",
        "slug": "aura-store",
        "tagline": "Moda contemporánea, prendas minimalistas y accesorios de autor en Lima.",
        "description": "Diseños atemporales confeccionados con materiales sostenibles. Envíos a todo el Perú y entregas inmediatas en Lima Metropolitana.",
        "logo": "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?w=300&auto=format&fit=crop&q=80",
        "banner": "https://images.unsplash.com/photo-1441986300917-64674bd600d8?w=1400&auto=format&fit=crop&q=80",
        "country_code": "51",
        "phone": "984512345",
        "currency": "PEN",
        "currency_symbol": "S/",
        "address": "Av. José Larco 812, Miraflores, Lima - Perú",
        "schedule": "Lunes a Sábado: 10:00 AM - 8:30 PM",
        "delivery_fee": 12.0,
        "free_delivery_threshold": 180.0,
        "allow_pickup": True,
        "payment_instructions": "Aceptamos pagos por Yape, Plin, transferencia BCP / BBVA y efectivo contra entrega.",
        "whatsapp_message_template": "🛍️ *¡HOLA {nombre_tienda}! NUEVO PEDIDO #{numero_pedido}*\nQuiero confirmar mi compra desde el catálogo digital:\n👤 *Comprador:* {nombre_cliente}\n📱 *Teléfono:* {telefono_cliente}\n📍 *Modalidad:* {tipo_entrega} ({direccion_entrega})\n💳 *Método de pago:* {metodo_pago}\n📋 *RESUMEN DE PRODUCTOS:*\n{lista_productos}\n💵 *Subtotal:* {subtotal}\n🚚 *Envío:* {costo_envio}\n💰 *TOTAL A PAGAR:* {total}\n💬 *Notas:* {notas_pedido}",
        "theme_color": "emerald",
        "socials": {"instagram": "@auraconcept.pe", "facebook": "auraconceptperu"}
    },
    {
        "id": "store_cafe",
        "name": "Origen & Tostaduría",
        "slug": "origen-cafe",
        "tagline": "Cafés de especialidad de origen peruano en grano o molido fresco y repostería artesanal.",
        "description": "Cafés de pequeños productores de Villa Rica, Cusco, Jaén y Cajamarca tostados semanalmente.",
        "logo": "https://images.unsplash.com/photo-1501339847302-ac426a4a7cbb?w=300&auto=format&fit=crop&q=80",
        "banner": "https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=1400&auto=format&fit=crop&q=80",
        "country_code": "51",
        "phone": "991234567",
        "currency": "PEN",
        "currency_symbol": "S/",
        "address": "Calle San Martín 380, Barranco, Lima - Perú",
        "schedule": "Lunes a Domingo: 8:00 AM - 8:00 PM",
        "delivery_fee": 8.0,
        "free_delivery_threshold": 90.0,
        "allow_pickup": True,
        "payment_instructions": "Transferencia bancaria BCP/BBVA, Yape o Plin.",
        "whatsapp_message_template": "☕ *¡HOLA {nombre_tienda}! NUEVO PEDIDO #{numero_pedido}*\n👤 *Cliente:* {nombre_cliente}\n📦 *ITEMS:*\n{lista_productos}\n💰 *TOTAL:* {total}",
        "theme_color": "amber",
        "socials": {"instagram": "@origencafe.pe"}
    },
    {
        "id": "store_urban",
        "name": "Urban Streetwear Co.",
        "slug": "urban-streetwear",
        "tagline": "Sneakers de colección, hoodies oversize y accesorios streetwear de edición limitada.",
        "description": "Drop mensual de prendas exclusivas para cultura urbana.",
        "logo": "https://images.unsplash.com/photo-1552346154-21d32810aba3?w=300&auto=format&fit=crop&q=80",
        "banner": "https://images.unsplash.com/photo-1556905055-8f358a7a47b2?w=1400&auto=format&fit=crop&q=80",
        "country_code": "51",
        "phone": "972345678",
        "currency": "PEN",
        "currency_symbol": "S/",
        "address": "C.C. Jockey Plaza, 2do Nivel, Surco, Lima",
        "schedule": "Lunes a Domingo: 11:00 AM - 9:00 PM",
        "delivery_fee": 15.0,
        "free_delivery_threshold": 250.0,
        "allow_pickup": True,
        "payment_instructions": "Yape, Plin y pagos con tarjeta de crédito/débito.",
        "whatsapp_message_template": "🔥 *¡HOLA {nombre_tienda}! NUEVO PEDIDO #{numero_pedido}*\n👤 *Cliente:* {nombre_cliente}\n{lista_productos}\n💰 *TOTAL:* {total}",
        "theme_color": "indigo",
        "socials": {"instagram": "@urbanstreetwear.pe"}
    }
]

INITIAL_PRODUCTS = [
    {
        "id": "prod_1",
        "store_id": "store_aura",
        "name": "Camisa Lino Oversize 'Brissa'",
        "slug": "camisa-lino-oversize-brissa",
        "description": "Confeccionada en 100% lino orgánico pre-lavado. Corte holgado con botones de madera reciclada.",
        "price": 149.0,
        "compare_at_price": 189.0,
        "category": "Moda & Ropa",
        "image_url": "https://images.unsplash.com/photo-1596755094514-f87e34085b2c?w=700&auto=format&fit=crop&q=80",
        "in_stock": True,
        "stock_count": 18,
        "is_featured": True,
        "views_count": 1840,
        "variants": [{"name": "Talla", "options": ["S", "M", "L"]}, {"name": "Color", "options": ["Blanco Natural", "Arena", "Oliva"]}]
    },
    {
        "id": "prod_2",
        "store_id": "store_aura",
        "name": "Pantalón Wide Leg de Algodón Pima",
        "slug": "pantalon-wide-leg-algodon-pima",
        "description": "Tiro alto con elástico posterior para ajuste perfecto. Tejido ligero y transpirable.",
        "price": 169.0,
        "compare_at_price": 210.0,
        "category": "Moda & Ropa",
        "image_url": "https://images.unsplash.com/photo-1509551388413-e18d0ac5d495?w=700&auto=format&fit=crop&q=80",
        "in_stock": True,
        "stock_count": 12,
        "is_featured": True,
        "views_count": 1420,
        "variants": [{"name": "Talla", "options": ["28", "30", "32"]}]
    },
    {
        "id": "prod_3",
        "store_id": "store_cafe",
        "name": "Café Geisha Villa Rica (Grano Entero 250g)",
        "slug": "cafe-geisha-villa-rica-250g",
        "description": "Variedad Geisha cosechada a 1,750 msnm. Notas a jazmín, bergamota, miel y durazno.",
        "price": 55.0,
        "compare_at_price": 65.0,
        "category": "Cafetería & Gourmet",
        "image_url": "https://images.unsplash.com/photo-1514432324607-a09d9b4aefdd?w=700&auto=format&fit=crop&q=80",
        "in_stock": True,
        "stock_count": 25,
        "is_featured": True,
        "views_count": 2100,
        "variants": [{"name": "Molienda", "options": ["En Grano", "Fina (Espresso)", "Media (V60/Chemex)", "Gruesa (Prensa)"]}]
    },
    {
        "id": "prod_4",
        "store_id": "store_urban",
        "name": "Hoodie Heavyweight Boxy 'Midnight'",
        "slug": "hoodie-heavyweight-boxy-midnight",
        "description": "Algodón perchado 450 GSM de máxima densidad. Fit boxy con hombros caídos y bordado tonal.",
        "price": 199.0,
        "compare_at_price": 240.0,
        "category": "Calzado & Sneakers",
        "image_url": "https://images.unsplash.com/photo-1556905055-8f358a7a47b2?w=700&auto=format&fit=crop&q=80",
        "in_stock": True,
        "stock_count": 8,
        "is_featured": True,
        "views_count": 2450,
        "variants": [{"name": "Talla", "options": ["M", "L", "XL"]}]
    }
]

INITIAL_BANNERS = [
    {
        "id": "banner_1",
        "title": "Drop Exclusivo: Nueva Colección de Lino y Algodón Pima",
        "subtitle": "Prendas de alta calidad con envío gratuito por compras mayores a S/ 180 en toda Lima.",
        "badge": "NUEVO INGRESO",
        "image_url": "https://images.unsplash.com/photo-1490481651871-ab68de25d43d?w=800&auto=format&fit=crop&q=80",
        "product_id": "prod_1",
        "store_id": "store_aura",
        "button_text": "Ver Colección",
        "gradient_theme": "emerald",
        "is_active": True,
        "order": 1
    },
    {
        "id": "banner_2",
        "title": "Café Geisha Especialidad - Cosecha Limitada 2026",
        "subtitle": "Micro-lotes premiados con notas a jazmín y durazno. Envíos frescos a domicilio.",
        "badge": "OFERTA LIMITADA",
        "image_url": "https://images.unsplash.com/photo-1447933601403-0c6688de566e?w=800&auto=format&fit=crop&q=80",
        "product_id": "prod_3",
        "store_id": "store_cafe",
        "button_text": "Pedir por WhatsApp",
        "gradient_theme": "amber",
        "is_active": True,
        "order": 2
    }
]

async def seed_data():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # Create SuperAdmin
        admin_stmt = select(User).where(User.email == "admin@jamuywasi.com")
        admin_user = (await session.execute(admin_stmt)).scalar_one_or_none()
        if not admin_user:
            admin_user = User(
                id="usr_superadmin",
                name="Super Administrador",
                email="admin@jamuywasi.com",
                hashed_password=hash_password("admin123"),
                role="superadmin",
                subscription_plan="business"
            )
            session.add(admin_user)
            print("SuperAdmin user created (admin@jamuywasi.com / admin123)")

        # Create Stores
        for s_data in INITIAL_STORES:
            stmt = select(Store).where(Store.id == s_data["id"])
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if not existing:
                store = Store(**s_data)
                session.add(store)
                print(f"Store seeded: {s_data['name']}")
                
                # Create merchant for this store
                merchant = User(
                    name=f"Admin {s_data['name']}",
                    email=f"contacto@{s_data['slug']}.com",
                    hashed_password=hash_password("tienda123"),
                    role="merchant",
                    store_id=s_data["id"],
                    subscription_plan="pro"
                )
                session.add(merchant)

        await session.flush()

        # Create Products
        for p_data in INITIAL_PRODUCTS:
            stmt = select(Product).where(Product.id == p_data["id"])
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if not existing:
                product = Product(**p_data)
                session.add(product)
                print(f"Product seeded: {p_data['name']}")

        # Create Banners
        for b_data in INITIAL_BANNERS:
            stmt = select(PromotionalBanner).where(PromotionalBanner.id == b_data["id"])
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if not existing:
                banner = PromotionalBanner(**b_data)
                session.add(banner)
                print(f"Banner seeded: {b_data['title']}")

        await session.commit()
        print("Initial database seed completed successfully!")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(seed_data())
