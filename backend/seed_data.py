import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
db_name = os.environ['DB_NAME']

async def seed_database():
    if os.environ.get("NUA_BOOKINGS_API_URL"):
        raise RuntimeError("Destructive demo seeding is disabled when booking synchronisation is configured")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    
    # Clear existing data
    print("Clearing existing data...")
    await db.products.delete_many({})
    await db.promotions.delete_many({})
    await db.customers.delete_many({})
    await db.transactions.delete_many({})
    await db.bas_reports.delete_many({})
    await db.locations.delete_many({})
    await db.users.delete_many({})
    await db.categories.delete_many({})
    await db.modifiers.delete_many({})

    # Seed Products
    print("Seeding products...")
    products = [
        {
            "id": "1",
            "name": "Espresso",
            "category": "Beverages",
            "price": 4.50,
            "cost": 1.20,
            "stock": 150,
            "sku": "BEV-ESP-001",
            "image": "https://images.unsplash.com/photo-1510591509098-f4fdc6d0ff04?w=200",
            "gstRate": 10,
            "modifiers": [
                {
                    "id": "mod-size",
                    "name": "Size",
                    "type": "single",
                    "required": True,
                    "options": [
                        {"id": "size-small", "name": "Small", "price": 0.0},
                        {"id": "size-medium", "name": "Medium", "price": 1.0},
                        {"id": "size-large", "name": "Large", "price": 2.0}
                    ]
                },
                {
                    "id": "mod-extras",
                    "name": "Extras",
                    "type": "multiple",
                    "required": False,
                    "options": [
                        {"id": "extra-shot", "name": "Extra Shot", "price": 1.5},
                        {"id": "extra-milk", "name": "Extra Milk", "price": 0.5}
                    ]
                }
            ],
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        },
        {
            "id": "2",
            "name": "Cappuccino",
            "category": "Beverages",
            "price": 5.00,
            "cost": 1.50,
            "stock": 200,
            "sku": "BEV-CAP-001",
            "image": "https://images.unsplash.com/photo-1572442388796-11668a67e53d?w=200",
            "gstRate": 10,
            "modifiers": [
                {
                    "id": "mod-size",
                    "name": "Size",
                    "type": "single",
                    "required": True,
                    "options": [
                        {"id": "size-small", "name": "Small", "price": 0.0},
                        {"id": "size-medium", "name": "Medium", "price": 1.0},
                        {"id": "size-large", "name": "Large", "price": 2.0}
                    ]
                }
            ],
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        },
        {
            "id": "3",
            "name": "Chocolate Cake",
            "category": "Bakery",
            "price": 6.50,
            "cost": 2.00,
            "stock": 50,
            "sku": "BAK-CHO-001",
            "image": "https://images.unsplash.com/photo-1578985545062-69928b1d9587?w=200",
            "gstRate": 10,
            "modifiers": [],
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        },
        {
            "id": "4",
            "name": "Beef Burger",
            "category": "Food",
            "price": 12.00,
            "cost": 4.50,
            "stock": 80,
            "sku": "FOD-BUR-001",
            "image": "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=200",
            "gstRate": 10,
            "modifiers": [
                {
                    "id": "mod-cooking",
                    "name": "Cooking Level",
                    "type": "single",
                    "required": True,
                    "options": [
                        {"id": "rare", "name": "Rare", "price": 0.0},
                        {"id": "medium", "name": "Medium", "price": 0.0},
                        {"id": "well-done", "name": "Well Done", "price": 0.0}
                    ]
                },
                {
                    "id": "mod-add-ons",
                    "name": "Add-ons",
                    "type": "multiple",
                    "required": False,
                    "options": [
                        {"id": "extra-cheese", "name": "Extra Cheese", "price": 2.0},
                        {"id": "bacon", "name": "Bacon", "price": 3.0},
                        {"id": "avocado", "name": "Avocado", "price": 2.5}
                    ]
                },
                {
                    "id": "mod-remove",
                    "name": "Remove",
                    "type": "multiple",
                    "required": False,
                    "options": [
                        {"id": "no-onions", "name": "No Onions", "price": 0.0},
                        {"id": "no-pickles", "name": "No Pickles", "price": 0.0},
                        {"id": "no-tomato", "name": "No Tomato", "price": 0.0}
                    ]
                }
            ],
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        },
        {
            "id": "5",
            "name": "Soft Drink",
            "category": "Beverages",
            "price": 3.50,
            "cost": 0.80,
            "stock": 300,
            "sku": "BEV-SOD-001",
            "image": "https://images.unsplash.com/photo-1629203851122-3726ecdf080e?w=200",
            "gstRate": 10,
            "modifiers": [],
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        },
        {
            "id": "6",
            "name": "Caesar Salad",
            "category": "Food",
            "price": 10.00,
            "cost": 3.50,
            "stock": 60,
            "sku": "FOD-SAL-001",
            "image": "https://images.unsplash.com/photo-1546793665-c74683f339c1?w=200",
            "gstRate": 10,
            "modifiers": [],
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        }
    ]
    await db.products.insert_many(products)
    
    # Seed Promotions
    print("Seeding promotions...")
    promotions = [
        {
            "id": "promo-1",
            "name": "Coffee & Cake Deal",
            "type": "bundle",
            "products": ["1", "3"],
            "originalPrice": 11.00,
            "discountedPrice": 9.00,
            "discount": 18,
            "active": True,
            "schedule": "All Day",
            "createdAt": datetime.utcnow()
        },
        {
            "id": "promo-2",
            "name": "Burger & Drink Combo",
            "type": "bundle",
            "products": ["4", "5"],
            "originalPrice": 15.50,
            "discountedPrice": 13.00,
            "discount": 16,
            "active": True,
            "schedule": "All Day",
            "createdAt": datetime.utcnow()
        },
        {
            "id": "promo-3",
            "name": "Happy Hour - 20% Off Beverages",
            "type": "category",
            "category": "Beverages",
            "discount": 20,
            "active": True,
            "schedule": "3:00 PM - 6:00 PM",
            "createdAt": datetime.utcnow()
        }
    ]
    await db.promotions.insert_many(promotions)
    
    # Seed Customers
    print("Seeding customers...")
    customers = [
        {
            "id": "cust-1",
            "name": "Sarah Johnson",
            "email": "sarah.j@email.com",
            "phone": "+61 412 345 678",
            "membershipTier": "Gold",
            "totalSpent": 2450.00,
            "visits": 87,
            "joinDate": datetime(2023, 6, 15),
            "points": 2450,
            "birthday": "1990-03-15",
            "company": "",
            "seatingPreference": "window",
            "dietaryRestrictions": ["Gluten-Free"],
            "allergies": ["Peanuts"],
            "favoriteDishes": ["Espresso", "Chocolate Cake", "Caesar Salad"],
            "tags": ["Regular", "High Spender"],
            "isVip": True,
            "notes": "Prefers quiet corner table. Always orders espresso first.",
            "noShowCount": 0,
            "avgSpendPerVisit": 28.16,
            "feedbackRating": 4.5,
            "feedbackCount": 3,
            "storeCredit": 0
        },
        {
            "id": "cust-2",
            "name": "Michael Chen",
            "email": "mchen@email.com",
            "phone": "+61 423 456 789",
            "membershipTier": "Platinum",
            "totalSpent": 5680.00,
            "visits": 156,
            "joinDate": datetime(2023, 1, 20),
            "points": 5680,
            "birthday": "1985-11-22",
            "company": "Chen Industries",
            "seatingPreference": "indoor",
            "dietaryRestrictions": [],
            "allergies": [],
            "favoriteDishes": ["Beef Burger", "Cappuccino", "Fish & Chips"],
            "tags": ["VIP", "Corporate", "Regular"],
            "isVip": True,
            "notes": "Top spender. Hosts business lunches often. Comp dessert on visits.",
            "noShowCount": 0,
            "avgSpendPerVisit": 36.41,
            "feedbackRating": 4.8,
            "feedbackCount": 5,
            "storeCredit": 25.00
        },
        {
            "id": "cust-3",
            "name": "Emma Wilson",
            "email": "emma.w@email.com",
            "phone": "+61 434 567 890",
            "membershipTier": "Silver",
            "totalSpent": 890.00,
            "visits": 34,
            "joinDate": datetime(2024, 3, 10),
            "points": 890,
            "birthday": "1995-07-08",
            "company": "",
            "seatingPreference": "outdoor",
            "dietaryRestrictions": ["Vegan"],
            "allergies": ["Milk", "Eggs"],
            "favoriteDishes": ["Garden Salad", "Mushroom Risotto"],
            "tags": ["Birthday Month"],
            "isVip": False,
            "notes": "Strict vegan. Birthday coming up in July.",
            "noShowCount": 1,
            "avgSpendPerVisit": 26.18,
            "feedbackRating": 4.0,
            "feedbackCount": 2,
            "storeCredit": 0
        },
        {
            "id": "cust-4",
            "name": "James Brown",
            "email": "jbrown@email.com",
            "phone": "+61 445 678 901",
            "membershipTier": "Bronze",
            "totalSpent": 245.00,
            "visits": 12,
            "joinDate": datetime(2024, 10, 5),
            "points": 245,
            "birthday": "",
            "company": "",
            "seatingPreference": "bar",
            "dietaryRestrictions": [],
            "allergies": [],
            "favoriteDishes": [],
            "tags": [],
            "isVip": False,
            "notes": "",
            "noShowCount": 2,
            "avgSpendPerVisit": 20.42,
            "feedbackRating": 0,
            "feedbackCount": 0,
            "storeCredit": 0
        }
    ]
    await db.customers.insert_many(customers)
    
    # Seed Transactions
    print("Seeding transactions...")
    transactions = [
        {
            "id": "TXN-20250115-001",
            "timestamp": datetime(2025, 1, 15, 9, 15, 32),
            "items": [
                {
                    "productId": "1", 
                    "productName": "Espresso", 
                    "quantity": 2, 
                    "price": 4.50,
                    "modifiers": []
                },
                {
                    "productId": "3", 
                    "productName": "Chocolate Cake", 
                    "quantity": 1, 
                    "price": 6.50,
                    "modifiers": []
                }
            ],
            "subtotal": 15.50,
            "discount": None,
            "discountAmount": 0.0,
            "gst": 1.55,
            "total": 17.05,
            "paymentMethod": "Card",
            "customerId": "cust-1",
            "customerName": "Sarah Johnson",
            "location": "Main Street",
            "cashier": "John Doe",
            "status": "completed",
            "printed": False
        },
        {
            "id": "TXN-20250115-002",
            "timestamp": datetime(2025, 1, 15, 9, 23, 18),
            "items": [
                {
                    "productId": "4", 
                    "productName": "Beef Burger", 
                    "quantity": 1, 
                    "price": 12.00,
                    "modifiers": [
                        {
                            "modifierId": "mod-cooking",
                            "modifierName": "Cooking Level",
                            "optionId": "medium",
                            "optionName": "Medium",
                            "price": 0.0
                        },
                        {
                            "modifierId": "mod-add-ons",
                            "modifierName": "Add-ons",
                            "optionId": "extra-cheese",
                            "optionName": "Extra Cheese",
                            "price": 2.0
                        }
                    ]
                },
                {
                    "productId": "5", 
                    "productName": "Soft Drink", 
                    "quantity": 1, 
                    "price": 3.50,
                    "modifiers": []
                }
            ],
            "subtotal": 17.50,
            "discount": None,
            "discountAmount": 0.0,
            "gst": 1.75,
            "total": 19.25,
            "paymentMethod": "Cash",
            "customerId": None,
            "customerName": None,
            "location": "Main Street",
            "cashier": "John Doe",
            "status": "completed",
            "printed": False
        },
        {
            "id": "TXN-20250115-003",
            "timestamp": datetime(2025, 1, 15, 9, 45, 7),
            "items": [
                {
                    "productId": "2", 
                    "productName": "Cappuccino", 
                    "quantity": 3, 
                    "price": 5.00,
                    "modifiers": []
                }
            ],
            "subtotal": 15.00,
            "discount": {
                "type": "percentage",
                "value": 10,
                "reason": "Loyal customer"
            },
            "discountAmount": 1.50,
            "gst": 1.35,
            "total": 14.85,
            "paymentMethod": "Digital Wallet",
            "customerId": "cust-2",
            "customerName": "Michael Chen",
            "location": "Mall Branch",
            "cashier": "Jane Smith",
            "status": "completed",
            "printed": True
        }
    ]
    await db.transactions.insert_many(transactions)
    
    # Seed Locations
    print("Seeding locations...")
    locations = [
        {
            "id": "loc-1",
            "name": "Main Street",
            "address": "123 Main St, Sydney NSW 2000",
            "phone": "+61 2 9876 5432",
            "status": "active"
        },
        {
            "id": "loc-2",
            "name": "Mall Branch",
            "address": "456 Shopping Mall, Sydney NSW 2001",
            "phone": "+61 2 9876 5433",
            "status": "active"
        }
    ]
    await db.locations.insert_many(locations)
    
    # Seed Users
    print("Seeding users...")
    users = [
        {
            "id": "user-1",
            "name": "John Doe",
            "email": "john@company.com",
            "role": "Admin",
            "locations": ["loc-1", "loc-2"],
            "status": "active"
        },
        {
            "id": "user-2",
            "name": "Jane Smith",
            "email": "jane@company.com",
            "role": "Cashier",
            "locations": ["loc-2"],
            "status": "active"
        },
        {
            "id": "user-3",
            "name": "Robert Wilson",
            "email": "robert@company.com",
            "role": "Accountant",
            "locations": ["loc-1", "loc-2"],
            "status": "active"
        }
    ]
    await db.users.insert_many(users)
    
    # Seed BAS Reports
    print("Seeding BAS reports...")
    bas_reports = [
        {
            "id": "bas-q4-2024",
            "quarter": "Q4 2024",
            "period": "Oct - Dec 2024",
            "totalSales": 145680.00,
            "gstCollected": 14568.00,
            "gstPaid": 3240.00,
            "netGst": 11328.00,
            "status": "submitted",
            "submittedDate": datetime(2025, 1, 28),
            "dueDate": datetime(2025, 2, 28),
            "transactionIds": [],
            "createdAt": datetime.utcnow()
        },
        {
            "id": "bas-q1-2025",
            "quarter": "Q1 2025",
            "period": "Jan - Mar 2025",
            "totalSales": 48920.00,
            "gstCollected": 4892.00,
            "gstPaid": 1120.00,
            "netGst": 3772.00,
            "status": "draft",
            "submittedDate": None,
            "dueDate": datetime(2025, 4, 28),
            "transactionIds": [],
            "createdAt": datetime.utcnow()
        }
    ]
    await db.bas_reports.insert_many(bas_reports)
    
    # Seed Categories
    print("Seeding categories...")
    categories = [
        {
            "id": "cat-1",
            "name": "Beverages",
            "description": "Hot and cold drinks",
            "color": "#3b82f6",
            "icon": "coffee",
            "sortOrder": 1,
            "active": True,
            "createdAt": datetime.utcnow()
        },
        {
            "id": "cat-2",
            "name": "Food",
            "description": "Main meals and snacks",
            "color": "#10b981",
            "icon": "utensils",
            "sortOrder": 2,
            "active": True,
            "createdAt": datetime.utcnow()
        },
        {
            "id": "cat-3",
            "name": "Bakery",
            "description": "Fresh baked goods",
            "color": "#f59e0b",
            "icon": "cake",
            "sortOrder": 3,
            "active": True,
            "createdAt": datetime.utcnow()
        }
    ]
    await db.categories.insert_many(categories)
    
    # ============ FLOOR PLANS ============
    print("Seeding floor plans...")
    today = datetime.utcnow().strftime('%Y-%m-%d')
    await db.floor_plans.delete_many({})
    await db.reservations.delete_many({})
    await db.waitlist.delete_many({})
    
    floor_plans = [
        {
            "id": "FP-MAIN",
            "name": "Main Dining",
            "locationId": None,
            "tables": [
                {"id": "TBL-01", "number": "1", "capacity": 2, "shape": "circle", "x": 80, "y": 80, "width": 60, "height": 60, "rotation": 0, "section": "Window", "status": "available", "isActive": True, "minCovers": 1, "maxCovers": 2},
                {"id": "TBL-02", "number": "2", "capacity": 2, "shape": "circle", "x": 200, "y": 80, "width": 60, "height": 60, "rotation": 0, "section": "Window", "status": "reserved", "isActive": True, "minCovers": 1, "maxCovers": 2},
                {"id": "TBL-03", "number": "3", "capacity": 4, "shape": "rectangle", "x": 350, "y": 60, "width": 90, "height": 70, "rotation": 0, "section": "Window", "status": "occupied", "isActive": True, "minCovers": 2, "maxCovers": 4},
                {"id": "TBL-04", "number": "4", "capacity": 4, "shape": "rectangle", "x": 80, "y": 220, "width": 90, "height": 70, "rotation": 0, "section": "Main", "status": "available", "isActive": True, "minCovers": 2, "maxCovers": 4},
                {"id": "TBL-05", "number": "5", "capacity": 4, "shape": "rectangle", "x": 230, "y": 220, "width": 90, "height": 70, "rotation": 0, "section": "Main", "status": "available", "isActive": True, "minCovers": 2, "maxCovers": 4},
                {"id": "TBL-06", "number": "6", "capacity": 6, "shape": "rectangle", "x": 380, "y": 220, "width": 110, "height": 70, "rotation": 0, "section": "Main", "status": "cleaning", "isActive": True, "minCovers": 4, "maxCovers": 6},
                {"id": "TBL-07", "number": "7", "capacity": 8, "shape": "rectangle", "x": 550, "y": 60, "width": 130, "height": 80, "rotation": 0, "section": "Private", "status": "reserved", "isActive": True, "minCovers": 6, "maxCovers": 8},
                {"id": "TBL-08", "number": "8", "capacity": 6, "shape": "rectangle", "x": 550, "y": 220, "width": 110, "height": 70, "rotation": 0, "section": "Private", "status": "available", "isActive": True, "minCovers": 4, "maxCovers": 6},
                {"id": "TBL-09", "number": "9", "capacity": 2, "shape": "circle", "x": 80, "y": 380, "width": 60, "height": 60, "rotation": 0, "section": "Bar", "status": "occupied", "isActive": True, "minCovers": 1, "maxCovers": 2},
                {"id": "TBL-10", "number": "10", "capacity": 2, "shape": "circle", "x": 200, "y": 380, "width": 60, "height": 60, "rotation": 0, "section": "Bar", "status": "available", "isActive": True, "minCovers": 1, "maxCovers": 2},
                {"id": "TBL-11", "number": "11", "capacity": 4, "shape": "square", "x": 350, "y": 370, "width": 70, "height": 70, "rotation": 0, "section": "Outdoor", "status": "available", "isActive": True, "minCovers": 2, "maxCovers": 4},
                {"id": "TBL-12", "number": "12", "capacity": 4, "shape": "square", "x": 460, "y": 370, "width": 70, "height": 70, "rotation": 0, "section": "Outdoor", "status": "available", "isActive": True, "minCovers": 2, "maxCovers": 4},
            ],
            "sections": [
                {"id": "SEC-WIN", "name": "Window", "color": "#3B82F6"},
                {"id": "SEC-MAIN", "name": "Main", "color": "#10B981"},
                {"id": "SEC-PRIV", "name": "Private", "color": "#8B5CF6"},
                {"id": "SEC-BAR", "name": "Bar", "color": "#F59E0B"},
                {"id": "SEC-OUT", "name": "Outdoor", "color": "#06B6D4"},
            ],
            "width": 1000,
            "height": 600,
            "isActive": True,
            "createdAt": datetime.utcnow().isoformat(),
            "updatedAt": datetime.utcnow().isoformat()
        }
    ]
    await db.floor_plans.insert_many(floor_plans)
    
    # ============ RESERVATIONS ============
    print("Seeding reservations...")
    reservations = [
        {"id": "RES-001", "guestName": "Sarah Mitchell", "guestPhone": "+61 412 345 678", "guestEmail": "sarah@email.com", "partySize": 2, "date": today, "time": "12:00", "duration": 90, "tableId": "TBL-02", "tableNumber": "2", "section": "Window", "status": "confirmed", "specialRequests": "Anniversary dinner, window seat preferred", "source": "phone", "tags": ["VIP"], "depositRequired": 0, "depositPaid": False, "noShowFee": 0, "createdAt": datetime.utcnow().isoformat(), "updatedAt": datetime.utcnow().isoformat()},
        {"id": "RES-002", "guestName": "James Chen", "guestPhone": "+61 423 456 789", "partySize": 4, "date": today, "time": "12:30", "duration": 120, "tableId": "TBL-03", "tableNumber": "3", "section": "Window", "status": "seated", "specialRequests": "Gluten-free options needed", "source": "online", "tags": ["dietary"], "depositRequired": 0, "depositPaid": False, "noShowFee": 0, "seatedAt": datetime.utcnow().isoformat(), "createdAt": datetime.utcnow().isoformat(), "updatedAt": datetime.utcnow().isoformat()},
        {"id": "RES-003", "guestName": "Emma Watson", "guestPhone": "+61 434 567 890", "guestEmail": "emma.w@email.com", "partySize": 6, "date": today, "time": "18:30", "duration": 120, "tableId": "TBL-07", "tableNumber": "7", "section": "Private", "status": "confirmed", "specialRequests": "Birthday celebration, need cake service", "source": "phone", "tags": ["birthday", "VIP"], "depositRequired": 50, "depositPaid": True, "noShowFee": 0, "createdAt": datetime.utcnow().isoformat(), "updatedAt": datetime.utcnow().isoformat()},
        {"id": "RES-004", "guestName": "David Park", "guestPhone": "+61 445 678 901", "partySize": 2, "date": today, "time": "19:00", "duration": 90, "section": "Main", "status": "confirmed", "source": "online", "tags": [], "depositRequired": 0, "depositPaid": False, "noShowFee": 0, "createdAt": datetime.utcnow().isoformat(), "updatedAt": datetime.utcnow().isoformat()},
        {"id": "RES-005", "guestName": "Lisa Thompson", "guestPhone": "+61 456 789 012", "guestEmail": "lisa.t@work.com", "partySize": 8, "date": today, "time": "19:30", "duration": 150, "section": "Private", "status": "confirmed", "specialRequests": "Business dinner, need projector", "source": "phone", "tags": ["corporate"], "depositRequired": 100, "depositPaid": True, "noShowFee": 0, "createdAt": datetime.utcnow().isoformat(), "updatedAt": datetime.utcnow().isoformat()},
        {"id": "RES-006", "guestName": "Michael Brown", "partySize": 2, "date": today, "time": "20:00", "duration": 90, "status": "confirmed", "source": "walk_in", "tags": [], "depositRequired": 0, "depositPaid": False, "noShowFee": 0, "createdAt": datetime.utcnow().isoformat(), "updatedAt": datetime.utcnow().isoformat()},
    ]
    await db.reservations.insert_many(reservations)
    
    # ============ WAITLIST ============
    print("Seeding waitlist...")
    waitlist = [
        {"id": "WL-001", "guestName": "Tom Harris", "guestPhone": "+61 401 111 222", "partySize": 3, "quotedWait": 15, "preferences": "indoor", "status": "waiting", "position": 1, "checkInTime": datetime.utcnow().isoformat(), "createdAt": datetime.utcnow().isoformat()},
        {"id": "WL-002", "guestName": "Anna Lee", "guestPhone": "+61 402 333 444", "partySize": 2, "quotedWait": 20, "preferences": "window", "status": "waiting", "position": 2, "notes": "Regular customer", "checkInTime": datetime.utcnow().isoformat(), "createdAt": datetime.utcnow().isoformat()},
        {"id": "WL-003", "guestName": "Kevin Zhang", "partySize": 5, "quotedWait": 30, "preferences": "outdoor", "status": "notified", "position": 3, "checkInTime": datetime.utcnow().isoformat(), "createdAt": datetime.utcnow().isoformat()},
    ]
    await db.waitlist.insert_many(waitlist)
    
    # ============ FEEDBACK ============
    print("Seeding feedback...")
    await db.feedback.delete_many({})
    feedback = [
        {"id": "FB-001", "customerId": "cust-1", "guestName": "Sarah Johnson", "rating": 5, "foodRating": 5, "serviceRating": 5, "ambienceRating": 4, "comment": "Absolutely wonderful experience! The espresso was perfect as always.", "tags": ["great-food"], "status": "responded", "response": "Thank you Sarah! We love having you.", "createdAt": datetime.utcnow().isoformat()},
        {"id": "FB-002", "customerId": "cust-1", "guestName": "Sarah Johnson", "rating": 4, "foodRating": 4, "serviceRating": 5, "ambienceRating": 4, "comment": "Great service but the cake was slightly dry today.", "tags": [], "status": "read", "createdAt": datetime.utcnow().isoformat()},
        {"id": "FB-003", "customerId": "cust-2", "guestName": "Michael Chen", "rating": 5, "foodRating": 5, "serviceRating": 5, "ambienceRating": 5, "comment": "Business lunch was impeccable. Your team is fantastic.", "tags": ["great-food", "excellent-service"], "status": "responded", "response": "Thank you Michael! Happy to host your team anytime.", "createdAt": datetime.utcnow().isoformat()},
        {"id": "FB-004", "customerId": "cust-3", "guestName": "Emma Wilson", "rating": 4, "foodRating": 4, "serviceRating": 4, "ambienceRating": 4, "comment": "Love the vegan options. Would love to see more variety.", "tags": [], "status": "new", "createdAt": datetime.utcnow().isoformat()},
    ]
    await db.feedback.insert_many(feedback)
    
    # ============ KITCHEN ORDERS ============
    print("Seeding kitchen orders...")
    await db.kitchen_orders.delete_many({})
    kitchen_orders = [
        {"id": "KO-001", "tableNumber": "3", "orderType": "dine_in", "items": [
            {"productId": "4", "productName": "Beef Burger", "quantity": 2, "course": 1, "status": "pending"},
            {"productId": "5", "productName": "Soft Drink", "quantity": 2, "course": 1, "status": "pending"}
        ], "notes": "No onions on one burger", "priority": "normal", "status": "new", "currentCourse": 1, "createdAt": datetime.utcnow().isoformat(), "estimatedMinutes": 15},
        {"id": "KO-002", "tableNumber": "7", "orderType": "dine_in", "items": [
            {"productId": "1", "productName": "Espresso", "quantity": 3, "course": 1, "status": "pending"},
            {"productId": "3", "productName": "Chocolate Cake", "quantity": 2, "course": 2, "status": "pending"},
            {"productId": "6", "productName": "Caesar Salad", "quantity": 1, "course": 1, "status": "pending"}
        ], "notes": "VIP table - birthday celebration", "priority": "vip", "status": "preparing", "currentCourse": 1, "startedAt": datetime.utcnow().isoformat(), "createdAt": datetime.utcnow().isoformat(), "estimatedMinutes": 20},
        {"id": "KO-003", "tableNumber": "9", "orderType": "dine_in", "items": [
            {"productId": "2", "productName": "Cappuccino", "quantity": 2, "course": 1, "status": "pending"}
        ], "priority": "normal", "status": "ready", "currentCourse": 1, "readyAt": datetime.utcnow().isoformat(), "createdAt": datetime.utcnow().isoformat(), "estimatedMinutes": 5},
        {"id": "KO-004", "orderType": "takeaway", "items": [
            {"productId": "4", "productName": "Beef Burger", "quantity": 1, "course": 1, "status": "pending"},
            {"productId": "7", "productName": "Fish & Chips", "quantity": 1, "course": 1, "status": "pending"}
        ], "notes": "Extra tartar sauce", "priority": "rush", "status": "new", "currentCourse": 1, "createdAt": datetime.utcnow().isoformat(), "estimatedMinutes": 12},
    ]
    await db.kitchen_orders.insert_many(kitchen_orders)

    # ============ LOYALTY REWARDS ============
    print("Seeding loyalty rewards...")
    await db.loyalty_rewards.delete_many({})
    await db.events.delete_many({})
    
    loyalty_rewards = [
        {"id": "RWD-001", "name": "Free Coffee", "description": "Any regular coffee on the house", "pointsCost": 50, "rewardType": "free_item", "discountAmount": 0, "isActive": True, "createdAt": datetime.utcnow().isoformat()},
        {"id": "RWD-002", "name": "$10 Off Next Visit", "description": "Discount on any order over $30", "pointsCost": 100, "rewardType": "discount", "discountAmount": 10, "isActive": True, "createdAt": datetime.utcnow().isoformat()},
        {"id": "RWD-003", "name": "Free Dessert", "description": "Complimentary dessert of your choice", "pointsCost": 150, "rewardType": "free_item", "discountAmount": 0, "isActive": True, "createdAt": datetime.utcnow().isoformat()},
        {"id": "RWD-004", "name": "Chef's Table Experience", "description": "Exclusive 5-course tasting menu with the chef", "pointsCost": 2000, "rewardType": "experience", "discountAmount": 0, "isActive": True, "createdAt": datetime.utcnow().isoformat()},
        {"id": "RWD-005", "name": "25% Off Entire Bill", "description": "Valid for parties up to 6", "pointsCost": 500, "rewardType": "discount", "discountPercent": 25, "isActive": True, "createdAt": datetime.utcnow().isoformat()},
    ]
    await db.loyalty_rewards.insert_many(loyalty_rewards)
    
    # ============ EVENTS ============
    print("Seeding events...")
    events = [
        {"id": "EVT-001", "name": "Wine & Dine: Italian Night", "description": "4-course Italian feast paired with premium wines from Tuscany", "date": "2026-03-15", "time": "19:00", "duration": 180, "capacity": 40, "ticketsBooked": 28, "ticketPrice": 89, "eventType": "wine_pairing", "isActive": True, "createdAt": datetime.utcnow().isoformat()},
        {"id": "EVT-002", "name": "Sushi Masterclass", "description": "Learn to roll sushi with our head chef. Includes all ingredients and sake tasting.", "date": "2026-03-22", "time": "14:00", "duration": 150, "capacity": 16, "ticketsBooked": 12, "ticketPrice": 120, "eventType": "cooking_class", "isActive": True, "createdAt": datetime.utcnow().isoformat()},
        {"id": "EVT-003", "name": "Jazz & Cocktails Friday", "description": "Live jazz trio with signature cocktail menu. No cover charge.", "date": "2026-03-07", "time": "20:00", "duration": 180, "capacity": 80, "ticketsBooked": 45, "ticketPrice": 0, "eventType": "live_music", "isActive": True, "createdAt": datetime.utcnow().isoformat()},
        {"id": "EVT-004", "name": "Corporate Tasting Dinner", "description": "Private dining experience for corporate groups with personalised menu.", "date": "2026-04-10", "time": "18:30", "duration": 240, "capacity": 30, "ticketsBooked": 0, "ticketPrice": 150, "eventType": "private", "isActive": True, "createdAt": datetime.utcnow().isoformat()},
    ]
    await db.events.insert_many(events)
    
    print("Database seeded successfully!")
    client.close()

if __name__ == "__main__":
    asyncio.run(seed_database())
