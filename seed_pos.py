import os
import django
import random
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from pos.models import Category, Product

def run():
    print("Seeding POS data...")
    
    # Categories
    categories = ['Electronics', 'Snacks', 'Beverages', 'Clothing']
    created_cats = []
    for cat_name in categories:
        cat, created = Category.objects.get_or_create(name=cat_name)
        created_cats.append(cat)
        if created:
            print(f"Created Category: {cat_name}")

    # Products
    products_data = [
        ('Cola', 'Beverages', 1.50, 100),
        ('Chips', 'Snacks', 2.00, 50),
        ('T-Shirt', 'Clothing', 15.00, 20),
        ('Headphones', 'Electronics', 49.99, 10),
        ('Water', 'Beverages', 0.99, 100),
        ('Chocolate Bar', 'Snacks', 1.25, 60),
    ]

    for name, cat_name, price, stock in products_data:
        cat = next(c for c in created_cats if c.name == cat_name)
        prod, created = Product.objects.get_or_create(
            name=name,
            defaults={
                'category': cat,
                'price': Decimal(str(price)),
                'stock': stock
            }
        )
        if created:
            print(f"Created Product: {name}")
    
    print("Done!")

if __name__ == '__main__':
    run()
