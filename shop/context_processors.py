from .cart import Cart
from .models import Favorite


def cart_count(request):
    cart = Cart(request)
    fav_count = 0
    if request.user.is_authenticated:
        fav_count = Favorite.objects.filter(user=request.user).count()
    return {
        'cart_total_items': len(cart),
        'fav_total_items': fav_count,
    }