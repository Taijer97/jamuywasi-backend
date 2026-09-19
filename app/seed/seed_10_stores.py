import asyncio
from datetime import datetime, timezone
import uuid
from sqlalchemy import select
from app.core.database import AsyncSessionLocal, engine, Base
from app.core.security import hash_password
from app.models.all_models import Store, Product, User

STORES_DATA = [
    {
        "user": {
            "name": "Lucía Morales",
            "email": "contacto@verdevivo.pe",
            "phone": "981112233",
        },
        "store": {
            "id": "store_verdevivo",
            "name": "Verde Vivo Botánica & Plantas",
            "slug": "verdevivo-botanica",
            "tagline": "Plantas de interior, suculentas y macetas de diseño para dar vida a tu hogar.",
            "description": "Cultivamos plantas sanas y felices adaptadas al clima limeño. Asesoría botánica personalizada por WhatsApp.",
            "logo": "https://images.unsplash.com/photo-1485955900006-10f4d324d411?w=300&auto=format&fit=crop&q=80",
            "banner": "https://images.unsplash.com/photo-1470058869958-2a77ade41c02?w=1400&auto=format&fit=crop&q=80",
            "phone": "981112233",
            "address": "Av. Pardo y Aliaga 450, San Isidro, Lima",
            "schedule": "Lunes a Sábado: 9:00 AM - 7:00 PM",
            "delivery_fee": 12.0,
            "free_delivery_threshold": 120.0,
            "theme_color": "emerald"
        },
        "products": [
            {
                "name": "Monstera Deliciosa en Maceta de Cerámica",
                "price": 89.0,
                "compare_at_price": 110.0,
                "category": "Plantas de Interior",
                "image_url": "https://images.unsplash.com/photo-1614594975525-e45190c55d0b?w=600&auto=format&fit=crop&q=80",
                "description": "Planta resistente de hojas perforadas icónicas. Incluye maceta artesanal blanca y plato drenador.",
                "stock_count": 15,
                "is_featured": True,
                "variants": [{"name": "Color Maceta", "options": ["Blanco Mate", "Terracota", "Gris Cemento"]}]
            },
            {
                "name": "Ficus Lyrata 'Hoja de Violín'",
                "price": 135.0,
                "compare_at_price": 160.0,
                "category": "Plantas de Interior",
                "image_url": "https://images.unsplash.com/photo-1597055181300-e3633a917c9c?w=600&auto=format&fit=crop&q=80",
                "description": "Hermosa planta de porte esbelto con grandes hojas lustrosas. Ideal para salas luminosas.",
                "stock_count": 8,
                "is_featured": True,
                "variants": [{"name": "Altura", "options": ["60 cm", "90 cm", "120 cm"]}]
            },
            {
                "name": "Kit de 4 Suculentas Variadas en Cuencos",
                "price": 45.0,
                "category": "Suculentas",
                "image_url": "https://images.unsplash.com/photo-1509423350716-97f9360b4e09?w=600&auto=format&fit=crop&q=80",
                "description": "Pack de 4 especies de fácil cuidado con sustrato especial para cactus y suculentas.",
                "stock_count": 25,
                "variants": []
            },
            {
                "name": "Maceta Artesanal Terracota Ondulada",
                "price": 38.0,
                "category": "Macetas & Deco",
                "image_url": "https://images.unsplash.com/photo-1514432324607-a09d9b4aefdd?w=600&auto=format&fit=crop&q=80",
                "description": "Elaborada a mano en arcilla natural horneada a alta temperatura. Excelente porosidad.",
                "stock_count": 20,
                "variants": [{"name": "Diámetro", "options": ["15 cm", "20 cm"]}]
            }
        ]
    },
    {
        "user": {
            "name": "Rodrigo Paz",
            "email": "ventas@kallpasneakers.pe",
            "phone": "982223344",
        },
        "store": {
            "id": "store_kallpa",
            "name": "Kallpa Sneaker & Street",
            "slug": "kallpa-sneakers",
            "tagline": "Zapatillas urbanas, calzado retro y accesorios para la cultura street.",
            "description": "Modelos exclusivos importados y nacionales de alta durabilidad con garantía de originalidad.",
            "logo": "https://images.unsplash.com/photo-1552346154-21d32810aba3?w=300&auto=format&fit=crop&q=80",
            "banner": "https://images.unsplash.com/photo-1556905055-8f358a7a47b2?w=1400&auto=format&fit=crop&q=80",
            "phone": "982223344",
            "address": "Calle Cantuarias 140, Miraflores, Lima",
            "schedule": "Lunes a Domingo: 11:00 AM - 8:30 PM",
            "delivery_fee": 10.0,
            "free_delivery_threshold": 180.0,
            "theme_color": "indigo"
        },
        "products": [
            {
                "name": "Retro Runner 90s Vintage Edition",
                "price": 220.0,
                "compare_at_price": 280.0,
                "category": "Calzado Urbano",
                "image_url": "https://images.unsplash.com/photo-1539185441755-769473a23570?w=600&auto=format&fit=crop&q=80",
                "description": "Suela de espuma EVA de alta amortiguación con paneles de gamuza sintética y malla respirable.",
                "stock_count": 14,
                "is_featured": True,
                "variants": [{"name": "Talla (US)", "options": ["8", "8.5", "9", "9.5", "10", "11"]}]
            },
            {
                "name": "Skate Pro Low Black & Gum",
                "price": 179.0,
                "category": "Calzado Urbano",
                "image_url": "https://images.unsplash.com/photo-1525966222134-fcfa99b8ae77?w=600&auto=format&fit=crop&q=80",
                "description": "Lona reforzada de doble costura con suela waffle vulcanizada antideslizante.",
                "stock_count": 20,
                "is_featured": True,
                "variants": [{"name": "Talla (US)", "options": ["7.5", "8", "9", "10"]}]
            },
            {
                "name": "Chunky Sneaker Cloud White",
                "price": 249.0,
                "compare_at_price": 299.0,
                "category": "Calzado Urbano",
                "image_url": "https://images.unsplash.com/photo-1595950653106-6c9ebd614d3a?w=600&auto=format&fit=crop&q=80",
                "description": "Silueta chunky con plantilla ergonómica de memoria. Estilo futurista para el día a día.",
                "stock_count": 9,
                "variants": [{"name": "Talla", "options": ["37", "38", "39", "40", "41"]}]
            },
            {
                "name": "Kit Limpiador Premium de Calzado con Cepillo",
                "price": 39.0,
                "category": "Accesorios",
                "image_url": "https://images.unsplash.com/photo-1588850561407-ed78c282e89b?w=600&auto=format&fit=crop&q=80",
                "description": "Espuma limpiadora biodegradable 200ml apta para cuero, lona, gamuza y nobuck.",
                "stock_count": 35,
                "variants": []
            }
        ]
    },
    {
        "user": {
            "name": "Camila Flores",
            "email": "pedidos@mishkipasteleria.pe",
            "phone": "983334455",
        },
        "store": {
            "id": "store_mishki",
            "name": "Mishki Dulces & Pastelería",
            "slug": "mishki-pasteleria",
            "tagline": "Tortas húmedas, alfajores de maicena y postres peruanos horneados con amor.",
            "description": "Ingredientes 100% naturales, manjar blanco de olla y chocolate belga. Envíos programados a domicilio.",
            "logo": "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=300&auto=format&fit=crop&q=80",
            "banner": "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?w=1400&auto=format&fit=crop&q=80",
            "phone": "983334455",
            "address": "Jr. Batalla de Junín 210, Barranco, Lima",
            "schedule": "Martes a Domingo: 10:00 AM - 7:30 PM",
            "delivery_fee": 8.0,
            "free_delivery_threshold": 95.0,
            "theme_color": "rose"
        },
        "products": [
            {
                "name": "Torta Húmeda de Chocolate Belga (10 porciones)",
                "price": 68.0,
                "compare_at_price": 80.0,
                "category": "Tortas Enteras",
                "image_url": "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=600&auto=format&fit=crop&q=80",
                "description": "Rellena con doble capa de fudge casero y ganache de chocolate al 60% de cacao cusqueño.",
                "stock_count": 10,
                "is_featured": True,
                "variants": [{"name": "Topping", "options": ["Fresas Frescas", "Virutas de Chocolate", "Sin Fruta"]}]
            },
            {
                "name": "Carrot Cake con Frosting de Queso Crema",
                "price": 62.0,
                "category": "Tortas Enteras",
                "image_url": "https://images.unsplash.com/photo-1621303837174-89787a7d4729?w=600&auto=format&fit=crop&q=80",
                "description": "Bizcocho especiado con canela, nueces tostadas y zanahoria fresca con crema suave philadelphia.",
                "stock_count": 12,
                "variants": []
            },
            {
                "name": "Caja de 12 Alfajores Artesanales de Maicena",
                "price": 32.0,
                "category": "Bocaditos & Alfajores",
                "image_url": "https://images.unsplash.com/photo-1558961363-fa8fdf82db35?w=600&auto=format&fit=crop&q=80",
                "description": "Masa extra suave que se deshace en la boca, rellena de abundante manjar blanco de olla.",
                "stock_count": 30,
                "is_featured": True,
                "variants": []
            },
            {
                "name": "Cheesecake Horneado de Frutos Rojos Silvestres",
                "price": 75.0,
                "compare_at_price": 89.0,
                "category": "Tortas Enteras",
                "image_url": "https://images.unsplash.com/photo-1533134242443-d4fd215305ad?w=600&auto=format&fit=crop&q=80",
                "description": "Base crujiente de galleta de mantequilla con coulis casero de moras, frambuesas y arándanos.",
                "stock_count": 8,
                "variants": []
            }
        ]
    },
    {
        "user": {
            "name": "Sebastián Wong",
            "email": "tienda@novatech.pe",
            "phone": "984445566",
        },
        "store": {
            "id": "store_novatech",
            "name": "NovaTech Gadgets & Audio",
            "slug": "novatech-gadgets",
            "tagline": "Audífonos inalámbricos, smartwatches, cargadores rápidos y periféricos para tu setup.",
            "description": "Garantía de 1 año en todos los productos electrónicos. Envíos express el mismo día en Lima.",
            "logo": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=300&auto=format&fit=crop&q=80",
            "banner": "https://images.unsplash.com/photo-1519389950473-47ba0277781c?w=1400&auto=format&fit=crop&q=80",
            "phone": "984445566",
            "address": "Av. República de Panamá 3560, San Isidro, Lima",
            "schedule": "Lunes a Sábado: 9:30 AM - 8:00 PM",
            "delivery_fee": 10.0,
            "free_delivery_threshold": 150.0,
            "theme_color": "emerald"
        },
        "products": [
            {
                "name": "Audífonos Wireless Noise Cancelling 'Pulse Pro'",
                "price": 189.0,
                "compare_at_price": 240.0,
                "category": "Audio & Sonido",
                "image_url": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=600&auto=format&fit=crop&q=80",
                "description": "Cancelación activa de ruido ANC de 35dB, batería de hasta 32 horas y almohadillas viscoelásticas.",
                "stock_count": 18,
                "is_featured": True,
                "variants": [{"name": "Color", "options": ["Negro Medianoche", "Plata Lunar", "Azul Marino"]}]
            },
            {
                "name": "Smartwatch AMOLED Deportivo 'Titan Fit'",
                "price": 169.0,
                "category": "Smartwatches",
                "image_url": "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=600&auto=format&fit=crop&q=80",
                "description": "Pantalla AMOLED HD táctil, monitor cardíaco 24/7, oxímetro SpO2 y resistencia al agua IP68.",
                "stock_count": 12,
                "is_featured": True,
                "variants": [{"name": "Correa", "options": ["Silicona Negra", "Gris Acero", "Verde Militar"]}]
            },
            {
                "name": "Batería Externa MagSafe Inalámbrica 10000mAh",
                "price": 119.0,
                "compare_at_price": 145.0,
                "category": "Cargadores & Cables",
                "image_url": "https://images.unsplash.com/photo-1609592424109-dd9892f1b177?w=600&auto=format&fit=crop&q=80",
                "description": "Fuerte agarre magnético, soporte trasero abatible y carga rápida USB-C Power Delivery 20W.",
                "stock_count": 22,
                "variants": []
            },
            {
                "name": "Soporte Ergonómico Plegable para Laptop",
                "price": 59.0,
                "category": "Setup & Oficina",
                "image_url": "https://images.unsplash.com/photo-1527864550417-7fd91fc51a46?w=600&auto=format&fit=crop&q=80",
                "description": "Construcción en aleación de aluminio premium con 6 niveles de inclinación y almohadillas de goma.",
                "stock_count": 40,
                "variants": [{"name": "Color", "options": ["Plata Espacial", "Gris Oscuro"]}]
            }
        ]
    },
    {
        "user": {
            "name": "Valeria Silva",
            "email": "hola@aromasdelvalle.pe",
            "phone": "985556677",
        },
        "store": {
            "id": "store_aromas",
            "name": "Aromas del Valle - Cosmética Natural",
            "slug": "aromas-del-valle",
            "tagline": "Cosmética botánica, jabones artesanales en frío y velas aromáticas de soya.",
            "description": "Fórmulas libres de parabenos, sulfatos y crueldad animal. Empaques ecológicos y aromas terapéuticos.",
            "logo": "https://images.unsplash.com/photo-1522335789203-aabd1fc54bc9?w=300&auto=format&fit=crop&q=80",
            "banner": "https://images.unsplash.com/photo-1608248597359-0091e921d3f0?w=1400&auto=format&fit=crop&q=80",
            "phone": "985556677",
            "address": "Calle 2 de Mayo 512, Miraflores, Lima",
            "schedule": "Lunes a Sábado: 10:00 AM - 7:00 PM",
            "delivery_fee": 9.0,
            "free_delivery_threshold": 110.0,
            "theme_color": "emerald"
        },
        "products": [
            {
                "name": "Sérum Facial Antioxidante Vitamina C & Rosa Mosqueta",
                "price": 79.0,
                "compare_at_price": 95.0,
                "category": "Cuidado Facial",
                "image_url": "https://images.unsplash.com/photo-1620916566398-39f1143ab7be?w=600&auto=format&fit=crop&q=80",
                "description": "Ilumina el rostro, combate manchas y aporta elasticidad con aceites prensados en frío de 30ml.",
                "stock_count": 25,
                "is_featured": True,
                "variants": []
            },
            {
                "name": "Pack Trío de Jabones Saponificados en Frío",
                "price": 42.0,
                "category": "Jabones & Baño",
                "image_url": "https://images.unsplash.com/photo-1607006314188-4694464c8d76?w=600&auto=format&fit=crop&q=80",
                "description": "Incluye: Avena y Miel, Carbón Activado Detox y Lavanda Relajante con base de aceite de oliva.",
                "stock_count": 30,
                "is_featured": True,
                "variants": []
            },
            {
                "name": "Vela Aromática de Cera de Soya 'Bosque Andino'",
                "price": 48.0,
                "category": "Velas & Aromaterapia",
                "image_url": "https://images.unsplash.com/photo-1603006905003-be475563bc59?w=600&auto=format&fit=crop&q=80",
                "description": "Pabilo de madera crepitante con aceites esenciales de eucalipto, pino y cedro en envase de vidrio.",
                "stock_count": 16,
                "variants": []
            },
            {
                "name": "Tónico Botánico de Rosas & Hamamelis 120ml",
                "price": 36.0,
                "category": "Cuidado Facial",
                "image_url": "https://images.unsplash.com/photo-1598440947619-2c35fc9aa908?w=600&auto=format&fit=crop&q=80",
                "description": "Equilibra el pH, cierra poros y refresca la piel cansada durante todo el día.",
                "stock_count": 20,
                "variants": []
            }
        ]
    },
    {
        "user": {
            "name": "Jimena Quispe",
            "email": "ventas@sisajoyeria.pe",
            "phone": "986667788",
        },
        "store": {
            "id": "store_sisa",
            "name": "Sisa Joyería Artesanal",
            "slug": "sisa-joyeria",
            "tagline": "Joyería contemporánea en Plata 950 peruana con piedras naturales de colección.",
            "description": "Orfebrería hecha a mano en Cusco y Lima. Cada pieza incluye certificado de autenticidad y caja de regalo.",
            "logo": "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?w=300&auto=format&fit=crop&q=80",
            "banner": "https://images.unsplash.com/photo-1515562141207-7a88fb7ce338?w=1400&auto=format&fit=crop&q=80",
            "phone": "986667788",
            "address": "Av. Conquistadores 780, San Isidro, Lima",
            "schedule": "Lunes a Sábado: 10:30 AM - 7:30 PM",
            "delivery_fee": 12.0,
            "free_delivery_threshold": 160.0,
            "theme_color": "purple"
        },
        "products": [
            {
                "name": "Collar Medalla Luna en Plata 950",
                "price": 129.0,
                "compare_at_price": 155.0,
                "category": "Collares & Dijes",
                "image_url": "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?w=600&auto=format&fit=crop&q=80",
                "description": "Cadena veneciana de 45cm con medalla grabada a mano y acabado brillante espejo.",
                "stock_count": 11,
                "is_featured": True,
                "variants": [{"name": "Largo Cadena", "options": ["40 cm", "45 cm", "50 cm"]}]
            },
            {
                "name": "Aretes Huggies de Plata con Circones Verdes",
                "price": 89.0,
                "category": "Aretes",
                "image_url": "https://images.unsplash.com/photo-1635767798638-3e25273a8236?w=600&auto=format&fit=crop&q=80",
                "description": "Aros pequeños con cierre a presión seguro, engaste francés con piedras esmeralda sintéticas.",
                "stock_count": 15,
                "is_featured": True,
                "variants": []
            },
            {
                "name": "Anillo Solitario con Cuarzo Rosa Natural",
                "price": 145.0,
                "compare_at_price": 175.0,
                "category": "Anillos",
                "image_url": "https://images.unsplash.com/photo-1605100804763-247f67b3557e?w=600&auto=format&fit=crop&q=80",
                "description": "Gema cabujón de cuarzo rosa facetado en montura de cuatro uñas de plata fina 950.",
                "stock_count": 7,
                "variants": [{"name": "Talla Anillo", "options": ["6", "7", "8"]}]
            },
            {
                "name": "Pulsera Minimalista Eslabón Figaro Plata",
                "price": 99.0,
                "category": "Pulseras",
                "image_url": "https://images.unsplash.com/photo-1611591475871-33230b6e9c99?w=600&auto=format&fit=crop&q=80",
                "description": "Diseño clásico y atemporal con broche tipo langosta de alta resistencia.",
                "stock_count": 14,
                "variants": []
            }
        ]
    },
    {
        "user": {
            "name": "Alonso Barreda",
            "email": "taller@biciandes.pe",
            "phone": "987778899",
        },
        "store": {
            "id": "store_biciandes",
            "name": "BiciAndes Taller & Ciclismo",
            "slug": "biciandes-ciclismo",
            "tagline": "Equipamiento para ciclistas urbanos, repuestos, cascos y accesorios de ruta.",
            "description": "Todo lo necesario para pedalear seguro y con estilo en la ciudad y en la montaña.",
            "logo": "https://images.unsplash.com/photo-1485965120184-e220f721d03e?w=300&auto=format&fit=crop&q=80",
            "banner": "https://images.unsplash.com/photo-1544197150-b99a580bb7a8?w=1400&auto=format&fit=crop&q=80",
            "phone": "987778899",
            "address": "Av. Arequipa 4120, Miraflores, Lima",
            "schedule": "Lunes a Sábado: 8:30 AM - 7:30 PM",
            "delivery_fee": 12.0,
            "free_delivery_threshold": 140.0,
            "theme_color": "indigo"
        },
        "products": [
            {
                "name": "Casco Aerodinámico Ultraligero con Visera",
                "price": 139.0,
                "compare_at_price": 175.0,
                "category": "Seguridad & Cascos",
                "image_url": "https://images.unsplash.com/photo-1557683316-973673baf926?w=600&auto=format&fit=crop&q=80",
                "description": "Espuma EPS de alta densidad con 21 canales de ventilación y luz LED trasera de advertencia.",
                "stock_count": 16,
                "is_featured": True,
                "variants": [{"name": "Talla", "options": ["M (54-58cm)", "L (58-62cm)"]}]
            },
            {
                "name": "Luz Delantera LED 1000 Lúmenes Recargable USB",
                "price": 69.0,
                "category": "Luces & Seguridad",
                "image_url": "https://images.unsplash.com/photo-1507035895480-2b3156c31fc8?w=600&auto=format&fit=crop&q=80",
                "description": "Cuerpo de aluminio resistente al agua IPX6 con 5 modos de iluminación y batería de 2600mAh.",
                "stock_count": 25,
                "is_featured": True,
                "variants": []
            },
            {
                "name": "Candado U-Lock Antirrobo con Cable de Acero",
                "price": 85.0,
                "category": "Accesorios",
                "image_url": "https://images.unsplash.com/photo-1485965120184-e220f721d03e?w=600&auto=format&fit=crop&q=80",
                "description": "Arco de acero endurecido de 14mm resistente a cizallas, incluye 3 llaves y soporte para cuadro.",
                "stock_count": 18,
                "variants": []
            },
            {
                "name": "Kit Multiherramienta 16 en 1 con Desarmadores",
                "price": 38.0,
                "category": "Herramientas",
                "image_url": "https://images.unsplash.com/photo-1581291518857-4e27b48ff24e?w=600&auto=format&fit=crop&q=80",
                "description": "Compacta y ligera, incluye llaves allen, destornilladores y tronchacadenas para emergencias.",
                "stock_count": 30,
                "variants": []
            }
        ]
    },
    {
        "user": {
            "name": "Milagros Cárdenas",
            "email": "atencion@qoribebe.pe",
            "phone": "988889900",
        },
        "store": {
            "id": "store_qori",
            "name": "Qori Bebé & Maternidad",
            "slug": "qori-bebe",
            "tagline": "Ropa en 100% algodón pima, juguetes didácticos y accesorios seguros para tu bebé.",
            "description": "Telas hipoalergénicas y tintes seguros certificados. Cuidamos la piel delicada de los más pequeños.",
            "logo": "https://images.unsplash.com/photo-1519689680058-324335c77eba?w=300&auto=format&fit=crop&q=80",
            "banner": "https://images.unsplash.com/photo-1515488042361-ee00e0ddd4e4?w=1400&auto=format&fit=crop&q=80",
            "phone": "988889900",
            "address": "Av. Benavides 2280, Miraflores, Lima",
            "schedule": "Lunes a Sábado: 10:00 AM - 7:00 PM",
            "delivery_fee": 10.0,
            "free_delivery_threshold": 130.0,
            "theme_color": "amber"
        },
        "products": [
            {
                "name": "Body Enterizo 100% Algodón Pima 'Osito'",
                "price": 49.0,
                "compare_at_price": 60.0,
                "category": "Ropa de Bebé",
                "image_url": "https://images.unsplash.com/photo-1522771930-78848d9293e8?w=600&auto=format&fit=crop&q=80",
                "description": "Extra suavidad que previene rozaduras. Broches libres de níquel para cambios de pañal sencillos.",
                "stock_count": 22,
                "is_featured": True,
                "variants": [{"name": "Talla", "options": ["0-3 meses", "3-6 meses", "6-12 meses"]}]
            },
            {
                "name": "Manta Térmica Tejida Antialérgica",
                "price": 58.0,
                "category": "Dormitorio & Cuna",
                "image_url": "https://images.unsplash.com/photo-1515488042361-ee00e0ddd4e4?w=600&auto=format&fit=crop&q=80",
                "description": "Manta de 90x100cm transpirable y cálida, lavable a máquina sin perder forma ni color.",
                "stock_count": 15,
                "is_featured": True,
                "variants": [{"name": "Color", "options": ["Celeste Pastel", "Rosa Bebé", "Beige Lino"]}]
            },
            {
                "name": "Sonajero Didáctico Montessori en Madera Natural",
                "price": 32.0,
                "category": "Juguetes & Estimulación",
                "image_url": "https://images.unsplash.com/photo-1596461404969-9ae70f2830c1?w=600&auto=format&fit=crop&q=80",
                "description": "Madera de haya pulida con cera de abeja natural sin barnices tóxicos para morder con seguridad.",
                "stock_count": 28,
                "variants": []
            },
            {
                "name": "Pack x3 Baberos Impermeables de Silicona de Grado Alimentario",
                "price": 39.0,
                "category": "Alimentación",
                "image_url": "https://images.unsplash.com/photo-1519689680058-324335c77eba?w=600&auto=format&fit=crop&q=80",
                "description": "Con bolsillo recolector de comida y cuello ajustable de 4 niveles. Limpieza al instante.",
                "stock_count": 20,
                "variants": []
            }
        ]
    },
    {
        "user": {
            "name": "Carlos 'Don Choche' Vera",
            "email": "pedidos@donchoche.pe",
            "phone": "989990011",
        },
        "store": {
            "id": "store_donchoche",
            "name": "Don Choche Carnes & Parrillas",
            "slug": "don-choche-parrillas",
            "tagline": "Cortes selectos Angus, chorizos artesanales, carbón y accesorios parrilleros.",
            "description": "Carnes empacadas al vacío con cadena de frío garantizada. Envíos el mismo día para tus asados.",
            "logo": "https://images.unsplash.com/photo-1544025162-d76694265947?w=300&auto=format&fit=crop&q=80",
            "banner": "https://images.unsplash.com/photo-1555939594-58d7cb561ad1?w=1400&auto=format&fit=crop&q=80",
            "phone": "989990011",
            "address": "Av. Primavera 1230, Surco, Lima",
            "schedule": "Miércoles a Domingo: 9:00 AM - 6:00 PM",
            "delivery_fee": 12.0,
            "free_delivery_threshold": 160.0,
            "theme_color": "dark"
        },
        "products": [
            {
                "name": "Bife Ancho Angus Prime (Corte de 500g)",
                "price": 65.0,
                "compare_at_price": 78.0,
                "category": "Cortes Premium",
                "image_url": "https://images.unsplash.com/photo-1558030006-450675393462?w=600&auto=format&fit=crop&q=80",
                "description": "Excelente marmoleo que garantiza jugosidad extrema a la brasa o a la plancha.",
                "stock_count": 18,
                "is_featured": True,
                "variants": [{"name": "Grosor", "options": ["1.5 pulgadas", "2 pulgadas"]}]
            },
            {
                "name": "Tomahawk Steak Angus 1kg con Hueso",
                "price": 120.0,
                "category": "Cortes Premium",
                "image_url": "https://images.unsplash.com/photo-1544025162-d76694265947?w=600&auto=format&fit=crop&q=80",
                "description": "El rey de la parrilla. Pieza imponente de costilla con veteado perfecto.",
                "stock_count": 8,
                "is_featured": True,
                "variants": []
            },
            {
                "name": "Pack x6 Chorizos Artesanales Finas Hierbas",
                "price": 34.0,
                "category": "Embutidos Artesanales",
                "image_url": "https://images.unsplash.com/photo-1555939594-58d7cb561ad1?w=600&auto=format&fit=crop&q=80",
                "description": "100% carne de cerdo seleccionada sin preservantes artificiales ni exceso de grasa.",
                "stock_count": 25,
                "variants": []
            },
            {
                "name": "Sal de Maras Parrillera Ahumada con Especerías 400g",
                "price": 22.0,
                "category": "Condimentos & Especias",
                "image_url": "https://images.unsplash.com/photo-1518977676601-b53f82aba655?w=600&auto=format&fit=crop&q=80",
                "description": "Sal fósil de los Andes peruanos ahumada en madera de roble con pimienta y romero.",
                "stock_count": 40,
                "variants": []
            }
        ]
    },
    {
        "user": {
            "name": "Renato Galindo",
            "email": "libros@elmanuscrito.pe",
            "phone": "980001122",
        },
        "store": {
            "id": "store_manuscrito",
            "name": "Librería El Manuscrito",
            "slug": "el-manuscrito-libros",
            "tagline": "Libros de narrativa, arte, cuadernos cosidos a mano y artículos de papelería fina.",
            "description": "Una curaduría literaria independiente con títulos especiales y papelería para mentes curiosas.",
            "logo": "https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?w=300&auto=format&fit=crop&q=80",
            "banner": "https://images.unsplash.com/photo-1507842229452-e25f82216503?w=1400&auto=format&fit=crop&q=80",
            "phone": "980001122",
            "address": "Calle Alcanfores 290, Miraflores, Lima",
            "schedule": "Lunes a Sábado: 10:00 AM - 8:00 PM",
            "delivery_fee": 8.0,
            "free_delivery_threshold": 80.0,
            "theme_color": "amber"
        },
        "products": [
            {
                "name": "Cuaderno Artesanal Cuero Cosido Copto (Hojas Marfil)",
                "price": 55.0,
                "compare_at_price": 68.0,
                "category": "Papelería de Autor",
                "image_url": "https://images.unsplash.com/photo-1544716278-ca5e3f4abd8c?w=600&auto=format&fit=crop&q=80",
                "description": "160 páginas de papel libre de ácido de 90g apto para pluma fuente, acuarela ligera y lápiz.",
                "stock_count": 18,
                "is_featured": True,
                "variants": [{"name": "Rayado", "options": ["Liso", "Puntos (Bullet)", "Rayas"]}]
            },
            {
                "name": "Pluma Estilográfica Vintage Classic 'Ebony'",
                "price": 89.0,
                "category": "Instrumentos de Escritura",
                "image_url": "https://images.unsplash.com/photo-1583485088034-697b5bc54ccd?w=600&auto=format&fit=crop&q=80",
                "description": "Plumín de acero inoxidable con punto fino F, cuerpo de resina pulida y convertidor de tinta incluido.",
                "stock_count": 14,
                "is_featured": True,
                "variants": [{"name": "Color Cuerpo", "options": ["Negro Ébano", "Azul Noche", "Burdeos"]}]
            },
            {
                "name": "Novela Gráfica 'El Retorno' Edición Tapa Dura",
                "price": 72.0,
                "category": "Libros & Novelas",
                "image_url": "https://images.unsplash.com/photo-1512820790803-83ca734da794?w=600&auto=format&fit=crop&q=80",
                "description": "Galardonada obra ilustrada a color en papel couché mate de 150g. Edición especial limitada.",
                "stock_count": 10,
                "variants": []
            },
            {
                "name": "Set de 4 Separadores de Libros Metálicos Dorados",
                "price": 28.0,
                "category": "Accesorios",
                "image_url": "https://images.unsplash.com/photo-1497633762265-9d179a990aa6?w=600&auto=format&fit=crop&q=80",
                "description": "Diseños geométricos grabados en latón dorado con acabado anticorrosivo brillante.",
                "stock_count": 30,
                "variants": []
            }
        ]
    }
]

async def seed_10_stores():
    print("Iniciando seed de 10 usuarios y tiendas con Plan Emprendedor...")
    async with AsyncSessionLocal() as db:
        for item in STORES_DATA:
            u_info = item["user"]
            s_info = item["store"]
            products_info = item["products"]

            # 1. Upsert Store
            stmt = select(Store).where(Store.slug == s_info["slug"])
            existing_store = (await db.execute(stmt)).scalar_one_or_none()

            if not existing_store:
                store = Store(
                    id=s_info["id"],
                    name=s_info["name"],
                    slug=s_info["slug"],
                    tagline=s_info["tagline"],
                    description=s_info["description"],
                    logo=s_info["logo"],
                    banner=s_info["banner"],
                    country_code="51",
                    phone=s_info["phone"],
                    currency="PEN",
                    currency_symbol="S/",
                    address=s_info["address"],
                    schedule=s_info["schedule"],
                    delivery_fee=s_info["delivery_fee"],
                    free_delivery_threshold=s_info["free_delivery_threshold"],
                    allow_pickup=True,
                    payment_instructions="Aceptamos Yape, Plin y transferencias bancarias directas.",
                    whatsapp_message_template="🛍️ *¡HOLA {nombre_tienda}! NUEVO PEDIDO #{numero_pedido}*\n👤 *Cliente:* {nombre_cliente}\n📦 *PRODUCTOS:*\n{lista_productos}\n💰 *TOTAL:* {total}",
                    theme_color=s_info.get("theme_color", "emerald"),
                    socials={"instagram": f"@{s_info['slug']}"},
                    is_active=True
                )
                db.add(store)
                await db.flush()
                print(f" -> Creada tienda: {store.name} ({store.slug})")
            else:
                store = existing_store
                store.name = s_info["name"]
                store.tagline = s_info["tagline"]
                store.description = s_info["description"]
                store.logo = s_info["logo"]
                store.banner = s_info["banner"]
                store.phone = s_info["phone"]
                store.address = s_info["address"]
                store.schedule = s_info["schedule"]
                print(f" -> Tienda existente actualizada: {store.name}")

            # 2. Upsert User (Plan Emprendedor = 'starter')
            user_stmt = select(User).where(User.email == u_info["email"])
            existing_user = (await db.execute(user_stmt)).scalar_one_or_none()

            if not existing_user:
                user = User(
                    name=u_info["name"],
                    email=u_info["email"],
                    hashed_password=hash_password("emprendedor123"),
                    role="merchant",
                    store_id=store.id,
                    phone=u_info["phone"],
                    status="active",
                    subscription_plan="starter"  # Plan Emprendedor
                )
                db.add(user)
                await db.flush()
                print(f"   -> Creado usuario comerciante: {user.email} con Plan Emprendedor (starter)")
            else:
                existing_user.store_id = store.id
                existing_user.subscription_plan = "starter"
                print(f"   -> Usuario actualizado: {existing_user.email}")

            # 3. Insert Products for this store
            for p_info in products_info:
                p_slug = f"{s_info['slug']}-{p_info['name'].lower().strip().replace(' ', '-')[:40]}"
                # check if exists
                p_stmt = select(Product).where((Product.store_id == store.id) & (Product.name == p_info["name"]))
                existing_prod = (await db.execute(p_stmt)).scalar_one_or_none()

                if not existing_prod:
                    prod = Product(
                        store_id=store.id,
                        name=p_info["name"],
                        slug=p_slug,
                        description=p_info["description"],
                        price=p_info["price"],
                        compare_at_price=p_info.get("compare_at_price"),
                        category=p_info["category"],
                        image_url=p_info["image_url"],
                        additional_images=[],
                        sku=f"SKU-{uuid.uuid4().hex[:6].upper()}",
                        in_stock=True,
                        stock_count=p_info.get("stock_count", 15),
                        is_featured=p_info.get("is_featured", False),
                        views_count=50,
                        variants=p_info.get("variants", [])
                    )
                    db.add(prod)
                    print(f"     + Producto: {prod.name} ({prod.price} S/)")

        await db.commit()
    print("Seed de 10 usuarios y tiendas con Plan Emprendedor completado con éxito.")

if __name__ == "__main__":
    asyncio.run(seed_10_stores())
