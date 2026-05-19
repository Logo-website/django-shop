from decimal import Decimal
from django.conf import settings
from .models import Product


class Cart:
    def __init__(self, request):
        self.session = request.session
        cart = self.session.get('cart')
        if not cart:
            cart = self.session['cart'] = {}
        self.cart = cart

    def add(self, product, quantity=1, update=False):
        product_id = str(product.id)
        if product_id not in self.cart:
            self.cart[product_id] = {'quantity': 0}  # цену не храним
        if update:
            self.cart[product_id]['quantity'] = quantity
        else:
            self.cart[product_id]['quantity'] += quantity
        self.save()

    def remove(self, product):
        product_id = str(product.id)
        if product_id in self.cart:
            del self.cart[product_id]
            self.save()

    def save(self):
        self.session.modified = True

    def __iter__(self):
        product_ids = self.cart.keys()
        products = Product.objects.filter(id__in=product_ids)
        products_map = {str(p.id): p for p in products}

        for product_id, item_data in self.cart.items():
            product = products_map.get(product_id)
            if product:
                item = dict(item_data)  # полная независимая копия
                item['product'] = product
                item['price'] = product.price
                item['total_price'] = product.price * item['quantity']
                yield item

    def __len__(self):
        return sum(item['quantity'] for item in self.cart.values())

    def get_total_price(self):
        product_ids = self.cart.keys()
        products = {
            str(p.id): p for p in Product.objects.filter(id__in=product_ids)
        }
        return sum(
            products[pid].price * item['quantity']
            for pid, item in self.cart.items()
            if pid in products
        )