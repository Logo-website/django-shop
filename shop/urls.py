from django.urls import path
from . import views

app_name = 'shop'

urlpatterns = [
    path('', views.product_list, name='product_list'),
    path('cart/', views.cart_detail, name='cart_detail'),
    path('cart/add/<int:product_id>/', views.cart_add, name='cart_add'),
    path('cart/remove/<int:product_id>/', views.cart_remove, name='cart_remove'),
    path('cart/update/<int:product_id>/', views.cart_update, name='cart_update'),
    path('order/', views.order_create, name='order_create'),
    path('register/', views.register_view, name='register'),
    path('register/verify/', views.register_verify, name='register_verify'),
    path('otp/', views.otp_verify, name='otp_verify'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('password-reset/', views.password_reset_request, name='password_reset_request'),
    path('password-reset/verify/', views.password_reset_verify, name='password_reset_verify'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
    path('profile/orders/', views.order_history, name='order_history'),
    path('favorites/', views.favorite_list, name='favorite_list'),
    path('favorites/add/<int:product_id>/', views.favorite_add, name='favorite_add'),
    path('favorites/remove/<int:product_id>/', views.favorite_remove, name='favorite_remove'),
    path('coupon/', views.coupon_apply, name='coupon_apply'),
    path('coupon/remove/', views.coupon_remove, name='coupon_remove'),
    path('api/search/', views.product_search_suggestions, name='search_suggestions'),
    path('<slug:category_slug>/', views.product_list, name='product_list_by_category'),
    path('<int:id>/<slug:slug>/', views.product_detail, name='product_detail'),
]