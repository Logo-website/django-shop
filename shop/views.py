import secrets
from datetime import datetime
from decimal import Decimal

import pytz
import resend
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Avg, Count, F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .cart import Cart
from .forms import (CouponForm, OrderForm, PasswordChangeFormCustom,
                    ProfileForm, RegisterForm, ReviewForm,
                    validate_password_strength)
from .models import (Category, Coupon, Favorite, Order, OrderItem, OTPCode,
                     Product, Review)


def safe_redirect(request, fallback='shop:product_list'):
    """Редирект на предыдущую страницу только если она на нашем домене."""
    referer = request.META.get('HTTP_REFERER')
    if referer and url_has_allowed_host_and_scheme(
        url=referer,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(referer)
    return redirect(fallback)


def product_list(request, category_slug=None):
    query = request.GET.get('q', '').strip()
    sort = request.GET.get('sort', 'rating')
    page_number = request.GET.get('page')

    category = None
    if category_slug:
        category = get_object_or_404(Category, slug=category_slug)

    products = Product.objects.filter(available=True)

    if category:
        products = products.filter(category=category)

    if query:
        products = products.filter(name__icontains=query)

    products = products.annotate(
        avg_rating=Avg('reviews__rating'),
        review_count=Count('reviews'),
    )

    if sort == 'price_asc':
        products = products.order_by('price')
    elif sort == 'price_desc':
        products = products.order_by('-price')
    elif sort == 'popular':
        products = products.annotate(order_count=Count('orderitem')).order_by('-order_count')
    elif sort == 'rating':
        products = products.order_by(F('avg_rating').desc(nulls_last=True))

    paginator = Paginator(products, 6)
    page_obj = paginator.get_page(page_number)

    categories = Category.objects.all()
    favorite_ids = []
    if request.user.is_authenticated:
        favorite_ids = Favorite.objects.filter(user=request.user).values_list('product_id', flat=True)

    return render(request, 'shop/product_list.html', {
        'category': category,
        'categories': categories,
        'products': page_obj,
        'query': query,
        'sort': sort,
        'favorite_ids': favorite_ids,
    })


def product_detail(request, id, slug):
    product = get_object_or_404(Product, id=id, slug=slug, available=True)
    reviews = product.reviews.select_related('user').all()
    user_review = None
    form = None

    has_purchased = False
    if request.user.is_authenticated:
        user_review = reviews.filter(user=request.user).first()
        has_purchased = OrderItem.objects.filter(
            order__user=request.user,
            product=product,
        ).exists()

        if not user_review and has_purchased:
            if request.method == 'POST':
                form = ReviewForm(request.POST)
                if form.is_valid():
                    review = form.save(commit=False)
                    review.product = product
                    review.user = request.user
                    review.save()
                    return redirect('shop:product_detail', id=product.id, slug=product.slug)
            else:
                form = ReviewForm()

    avg_rating = None
    if reviews.exists():
        avg_rating = reviews.aggregate(Avg('rating'))['rating__avg']

    return render(request, 'shop/product_detail.html', {
        'product': product,
        'reviews': reviews,
        'form': form,
        'user_review': user_review,
        'avg_rating': avg_rating,
        'has_purchased': has_purchased,
    })


def cart_detail(request):
    cart = Cart(request)
    coupon_form = CouponForm()
    coupon = None
    discount = 0
    coupon_error = request.session.pop('coupon_error', None)

    coupon_id = request.session.get('coupon_id')
    if coupon_id:
        try:
            coupon = Coupon.objects.get(id=coupon_id, active=True)
            discount = coupon.discount
        except Coupon.DoesNotExist:
            request.session['coupon_id'] = None

    total = cart.get_total_price()
    discount_amount = total * discount / 100
    total_after_discount = total - discount_amount

    return render(request, 'shop/cart_detail.html', {
        'cart': cart,
        'coupon_form': coupon_form,
        'coupon': coupon,
        'discount_amount': discount_amount,
        'total_after_discount': total_after_discount,
        'coupon_error': coupon_error,
    })


def cart_add(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id, available=True)
    cart.add(product)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'product_name': product.name,
            'cart_total': len(cart),
        })

    messages.success(request, f'«{product.name}» добавлен в корзину')
    return safe_redirect(request)


@require_POST
def cart_remove(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    cart.remove(product)
    return redirect('shop:cart_detail')


def order_create(request):
    cart = Cart(request)

    if not len(cart):
        return redirect('shop:cart_detail')

    if request.user.is_authenticated:
        if not request.user.first_name or not request.user.profile.phone:
            messages.warning(request, 'Пожалуйста, заполните имя и телефон перед оформлением заказа.')
            return redirect(f"{reverse('shop:profile_edit')}?from=order")

    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            if request.user.is_authenticated:
                order.user = request.user
                order.first_name = request.user.first_name or request.user.username
                order.phone = getattr(request.user.profile, 'phone', '')

            coupon_id = request.session.get('coupon_id')
            if coupon_id:
                try:
                    now = timezone.now()
                    coupon = Coupon.objects.get(
                        id=coupon_id,
                        active=True,
                        valid_from__lte=now,
                        valid_to__gte=now,
                    )
                    order.coupon = coupon
                    order.discount = coupon.discount
                except Coupon.DoesNotExist:
                    pass

            order.save()
            for item in cart:
                OrderItem.objects.create(
                    order=order,
                    product=item['product'],
                    price=item['product'].price,
                    quantity=item['quantity'],
                )

            request.session['cart'] = {}
            request.session.pop('coupon_id', None)
            request.session.modified = True

            order = Order.objects.prefetch_related('items__product').get(pk=order.pk)

            if order.user and order.user.email:
                print('=' * 50)
                print(f'ПИСЬМО ДЛЯ: {order.user.email}')
                print(f'ТЕМА: Заказ №{order.id} оформлен')
                print('-' * 50)
                print(f'Здравствуйте, {order.first_name}!')
                print()
                print(f'Ваш заказ №{order.id} успешно оформлен.')
                print(f'Сумма: {order.get_total_cost()} руб.')
                print(f'Адрес доставки: {order.address}')
                print()
                print('Спасибо за покупку!')
                print('=' * 50)

            return render(request, 'shop/order_created.html', {'order': order})
    else:
        form = OrderForm()

    coupon = None
    discount_amount = Decimal('0')
    total_after_discount = cart.get_total_price()

    coupon_id = request.session.get('coupon_id')
    if coupon_id:
        try:
            coupon = Coupon.objects.get(id=coupon_id, active=True)
            discount_amount = cart.get_total_price() * Decimal(coupon.discount) / 100
            total_after_discount = cart.get_total_price() - discount_amount
        except Coupon.DoesNotExist:
            pass

    return render(request, 'shop/order_create.html', {
        'cart': cart,
        'form': form,
        'coupon': coupon,
        'discount_amount': discount_amount,
        'total_after_discount': total_after_discount,
    })


def register_view(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False
            user.save()

            code = f'{secrets.randbelow(10 ** 6):06d}'
            OTPCode.objects.create(user=user, code_hash=OTPCode.hash_code(code))

            request.session['pending_user_id'] = user.id

            resend.api_key = settings.RESEND_API_KEY
            try:
                resend.Emails.send({
                    'from': 'noreply@progardengreen.ru',
                    'to': [user.email],
                    'subject': 'Подтверждение регистрации — Зелёный Сад',
                    'html': f'<p>Для завершения регистрации введите код:</p><p><strong style="font-size:24px">{code}</strong></p><p>Код действителен 10 минут.</p>',
                })
            except Exception as e:
                print(f'Ошибка отправки: {e}')

            return redirect('shop:register_verify')
    else:
        form = RegisterForm()
    return render(request, 'shop/register.html', {'form': form})


def register_verify(request):
    user_id = request.session.get('pending_user_id')
    if not user_id:
        return redirect('shop:register')

    try:
        user = User.objects.get(id=user_id, is_active=False)
    except User.DoesNotExist:
        request.session.pop('pending_user_id', None)
        return redirect('shop:register')

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        otp = OTPCode.objects.filter(user=user, is_used=False).last()

        if otp and otp.is_valid() and otp.check_code(code):
            user.is_active = True
            user.save()
            otp.is_used = True
            otp.save()
            request.session.pop('pending_user_id', None)
            login(request, user)
            return redirect('shop:product_list')
        else:
            return render(request, 'shop/register_verify.html', {
                'error': 'Неверный или истёкший код.',
                'email': user.email,
            })

    return render(request, 'shop/register_verify.html', {'email': user.email})

def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        try:
            user_obj = User.objects.get(email=email)
            if not user_obj.is_active:
                return render(request, 'shop/login.html', {
                    'error': 'Аккаунт не подтверждён. Завершите регистрацию по ссылке из письма.'
                })
            user = authenticate(request, username=user_obj.username, password=password)
            if user is not None:
                OTPCode.objects.filter(user=user, is_used=False).update(is_used=True)

                code = f'{secrets.randbelow(10 ** 6):06d}'
                OTPCode.objects.create(user=user, code_hash=OTPCode.hash_code(code))
                request.session['otp_user_id'] = user.id

                resend.api_key = settings.RESEND_API_KEY
                try:
                    resend.Emails.send({
                        'from': 'noreply@progardengreen.ru',
                        'to': [user.email],
                        'subject': 'Код входа — Зелёный Сад',
                        'html': f'<p>Здравствуйте, {user.first_name or user.username}!</p><p>Ваш код входа: <strong style="font-size:24px">{code}</strong></p><p>Код действителен 10 минут.</p>',
                    })
                except Exception as e:
                    print(f'Ошибка отправки OTP: {e}')
                return redirect('shop:otp_verify')
            else:
                return render(request, 'shop/login.html', {'error': 'Неверный email или пароль.'})
        except User.DoesNotExist:
            return render(request, 'shop/login.html', {'error': 'Неверный email или пароль.'})
    return render(request, 'shop/login.html')


def otp_verify(request):
    user_id = request.session.get('otp_user_id')
    if not user_id:
        return redirect('shop:login')

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        try:
            user = User.objects.get(id=user_id)
            otp = OTPCode.objects.filter(user=user, is_used=False).last()
            if otp and otp.is_valid() and otp.check_code(code):
                otp.is_used = True
                otp.save()
                del request.session['otp_user_id']
                login(request, user)
                return redirect('shop:product_list')
            else:
                return render(request, 'shop/otp_verify.html', {'error': 'Неверный или истёкший код.'})
        except User.DoesNotExist:
            return redirect('shop:login')

    return render(request, 'shop/otp_verify.html')

def logout_view(request):
    logout(request)
    return redirect('shop:product_list')


@login_required(login_url='shop:login')
def profile_view(request):
    orders = Order.objects.filter(user=request.user).prefetch_related('items__product').order_by('-created')
    return render(request, 'shop/profile.html', {'orders': orders})


@require_POST
@login_required(login_url='shop:login')
def favorite_add(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    Favorite.objects.get_or_create(user=request.user, product=product)
    return safe_redirect(request)


@require_POST
@login_required(login_url='shop:login')
def favorite_remove(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    Favorite.objects.filter(user=request.user, product=product).delete()
    return safe_redirect(request)


@login_required(login_url='shop:login')
def favorite_list(request):
    favorites = Favorite.objects.filter(user=request.user).select_related('product')
    return render(request, 'shop/favorite_list.html', {'favorites': favorites})


def coupon_apply(request):
    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        now = timezone.now()
        try:
            coupon = Coupon.objects.get(
                code__iexact=code,
                active=True,
                valid_from__lte=now,
                valid_to__gte=now,
            )
            if request.user.is_authenticated:
                already_used = Order.objects.filter(
                    user=request.user,
                    coupon=coupon,
                ).exists()
                if already_used:
                    request.session['coupon_id'] = None
                    request.session['coupon_error'] = 'Этот купон уже был использован вами ранее.'
                    return redirect('shop:cart_detail')

            request.session['coupon_id'] = coupon.id

        except Coupon.DoesNotExist:
            request.session['coupon_id'] = None
            request.session['coupon_error'] = 'Купон не найден или истёк.'

    return redirect('shop:cart_detail')


@require_POST
def coupon_remove(request):
    request.session['coupon_id'] = None
    request.session.modified = True
    return redirect('shop:cart_detail')


@require_POST
def cart_update(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id, available=True)
    action = request.POST.get('action')

    product_id_str = str(product.id)
    current_qty = cart.cart.get(product_id_str, {}).get('quantity', 0)

    if action == 'increase':
        cart.add(product, quantity=current_qty + 1, update=True)
    elif action == 'decrease' and current_qty > 1:
        cart.add(product, quantity=current_qty - 1, update=True)

    return redirect('shop:cart_detail')


@login_required(login_url='shop:login')
def profile_edit(request):
    user = request.user
    profile = user.profile
    missing_fields = []

    if request.method == 'POST' and 'save_profile' in request.POST:
        form = ProfileForm(request.POST, user=user)
        password_form = PasswordChangeFormCustom(user)
        if form.is_valid():
            user.first_name = form.cleaned_data['first_name']
            user.email = form.cleaned_data['email']
            user.save()
            profile.phone = form.cleaned_data['phone']
            profile.save()
            return redirect('shop:profile_edit')
        return render(request, 'shop/profile_edit.html', {
            'form': form,
            'password_form': password_form,
            'missing_fields': missing_fields,
        })

    elif request.method == 'POST' and 'change_password' in request.POST:
        form = ProfileForm(initial={
            'first_name': user.first_name,
            'phone': profile.phone,
            'email': user.email,
        }, user=user)
        password_form = PasswordChangeFormCustom(user, request.POST)
        if password_form.is_valid():
            user.set_password(password_form.cleaned_data['new_password1'])
            user.save()
            update_session_auth_hash(request, user)
            return redirect('shop:profile_edit')
        return render(request, 'shop/profile_edit.html', {
            'form': form,
            'password_form': password_form,
            'missing_fields': missing_fields,
        })

    else:
        form = ProfileForm(initial={
            'first_name': user.first_name,
            'phone': profile.phone,
            'email': user.email,
        }, user=user)
        password_form = PasswordChangeFormCustom(user)

        if request.GET.get('from') == 'order':
            if not user.first_name:
                missing_fields.append('first_name')
            if not profile.phone:
                missing_fields.append('phone')

        return render(request, 'shop/profile_edit.html', {
            'form': form,
            'password_form': password_form,
            'missing_fields': missing_fields,
        })


@login_required(login_url='shop:login')
def order_history(request):
    orders = Order.objects.filter(user=request.user).prefetch_related('items__product').order_by('-created')
    return render(request, 'shop/order_history.html', {'orders': orders})


def password_reset_request(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        try:
            user = User.objects.get(email=email)
            code = f'{secrets.randbelow(10 ** 6):06d}'
            request.session['reset_user_id'] = user.id
            request.session['reset_code'] = code
            request.session['reset_time'] = str(timezone.now())

            resend.api_key = settings.RESEND_API_KEY
            try:
                resend.Emails.send({
                    'from': 'noreply@progardengreen.ru',
                    'to': [user.email],
                    'subject': 'Восстановление пароля — Зелёный Сад',
                    'html': f'<p>Здравствуйте!</p><p>Ваш код для восстановления пароля: <strong style="font-size:24px">{code}</strong></p><p>Код действителен 10 минут.</p>',
                })
            except Exception as e:
                print(f'Ошибка: {e}')
            return redirect('shop:password_reset_verify')
        except User.DoesNotExist:
            return render(request, 'shop/password_reset.html', {'error': 'Аккаунт с таким email не найден.'})
    return render(request, 'shop/password_reset.html')


def password_reset_verify(request):
    user_id = request.session.get('reset_user_id')
    if not user_id:
        return redirect('shop:password_reset_request')

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        new_password = request.POST.get('new_password', '')
        new_password2 = request.POST.get('new_password2', '')
        saved_code = request.session.get('reset_code')
        saved_time = request.session.get('reset_time')

        otp_time = datetime.fromisoformat(saved_time).replace(tzinfo=pytz.UTC)
        elapsed = (timezone.now() - otp_time).total_seconds()

        if code != saved_code or elapsed >= 600:
            return render(request, 'shop/password_reset_verify.html', {'error': 'Неверный или истёкший код.'})

        if new_password != new_password2:
            return render(request, 'shop/password_reset_verify.html', {'error': 'Пароли не совпадают.'})

        try:
            validate_password_strength(new_password)
        except ValidationError as e:
            return render(request, 'shop/password_reset_verify.html', {'error': e.messages[0]})

        user = User.objects.get(id=user_id)
        user.set_password(new_password)
        user.save()

        for key in ['reset_user_id', 'reset_code', 'reset_time']:
            request.session.pop(key, None)

        return render(request, 'shop/password_reset_done.html')

    return render(request, 'shop/password_reset_verify.html')


def product_search_suggestions(request):
    query = request.GET.get('q', '').strip()
    if len(query) < 1:
        return JsonResponse({'results': []})

    matching = Product.objects.filter(available=True, name__istartswith=query)[:7]

    results = [{
        'id': p.id,
        'name': p.name,
        'slug': p.slug,
        'price': str(p.price),
        'image': p.image.url if p.image else '',
        'url': f'/{p.id}/{p.slug}/',
    } for p in matching]

    return JsonResponse({'results': results})