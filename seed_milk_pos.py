import os
import django
import random
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from pos.models import Product, Category, Order, OrderItem

def seed_milk_products():
    print("Clearing existing POS data...")
    OrderItem.objects.all().delete()
    Order.objects.all().delete()
    Product.objects.all().delete()
    Category.objects.all().delete()
    
    print("Creating Milk Shop Categories...")
    categories = [
        "Fresh Milk",
        "Flavored Milk",
        "Yogurt & Smoothies",
        "Toppings"
    ]
    
    cat_objs = {}
    for c in categories:
        cat_objs[c] = Category.objects.create(name=c)
        
    print("Creating Milk Products...")
    products = [
        # Fresh Milk
        {"name": "Fresh Milk (Glass)", "price": 45.00, "cat": "Fresh Milk", "image": "fresh_milk.jpg"},
        {"name": "Fresh Milk (Bottle)", "price": 85.00, "cat": "Fresh Milk", "image": "fresh_milk_bottle.jpg"},
        {"name": "Hot Milk", "price": 35.00, "cat": "Fresh Milk", "image": "hot_milk.jpg"},
        
        # Flavored
        {"name": "Chocolate Milk", "price": 50.00, "cat": "Flavored Milk", "image": "choco_milk.jpg"},
        {"name": "Strawberry Milk", "price": 50.00, "cat": "Flavored Milk", "image": "straw_milk.jpg"},
        {"name": "Banana Milk", "price": 50.00, "cat": "Flavored Milk", "image": "banana_milk.jpg"},
        {"name": "Matcha Latte", "price": 60.00, "cat": "Flavored Milk", "image": "matcha.jpg"},
        {"name": "Thai Tea Milk", "price": 55.00, "cat": "Flavored Milk", "image": "thai_tea.jpg"},
        
        # Yogurt
        {"name": "Plain Yogurt", "price": 40.00, "cat": "Yogurt & Smoothies", "image": "yogurt.jpg"},
        {"name": "Berry Smoothie", "price": 75.00, "cat": "Yogurt & Smoothies", "image": "berry_smoothie.jpg"},
        
        # Toppings
        {"name": "Honey Jelly", "price": 10.00, "cat": "Toppings", "image": "jelly.jpg"},
        {"name": "Brown Sugar Pearl", "price": 15.00, "cat": "Toppings", "image": "pearl.jpg"},
        {"name": "Pudding", "price": 20.00, "cat": "Toppings", "image": "pudding.jpg"},
    ]
    
    for p in products:
        Product.objects.create(
            name=p['name'],
            price=p['price'],
            category=cat_objs[p['cat']],
            stock=100,
            code=f"M{random.randint(1000,9999)}"
        )
        
    print("Milk Shop Seeded Successfully!")

if __name__ == '__main__':
    seed_milk_products()
