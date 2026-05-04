from django.core.mail import send_mail
from django.utils import timezone
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from .models import Category, Product, OrderItem, Review, Order, Favorite, Coupon
from .forms import OrderForm, ReviewForm, RegisterForm, CouponForm
from .cart import Cart
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse


def product_list(request, category_slug=None):
    category = None
    categories = Category.objects.all()
    products = Product.objects.filter(available=True)

    query = request.GET.get('q')
    if query:
        q_lower = query.lower()
        matching_ids = [p.id for p in products if q_lower in p.name.lower()]
        products = products.filter(id__in=matching_ids)

    if category_slug:
        category = get_object_or_404(Category, slug=category_slug)
        products = products.filter(category=category)

    from django.db.models import Avg, Count
    products = products.annotate(
        avg_rating=Avg('reviews__rating'),
        review_count=Count('reviews'),
    )

    sort = request.GET.get('sort', 'rating')
    if sort == 'price_asc':
        products = products.order_by('price')
    elif sort == 'price_desc':
        products = products.order_by('-price')
    elif sort == 'popular':
        products = products.annotate(order_count=Count('orderitem')).order_by('-order_count')
    elif sort == 'rating':
        from django.db.models import F
        products = products.order_by(F('avg_rating').desc(nulls_last=True))

    paginator = Paginator(products, 6)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

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
    reviews = product.reviews.all()
    user_review = None
    form = None

    has_purchased = False
    if request.user.is_authenticated:
        user_review = reviews.filter(user=request.user).first()
        # Проверяем покупал ли пользователь этот товар
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
        from django.db.models import Avg
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
    product = get_object_or_404(Product, id=product_id)
    cart.add(product)
    return redirect('shop:cart_detail')


def cart_remove(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    cart.remove(product)
    return redirect('shop:cart_detail')


def order_create(request):
    cart = Cart(request)

    if request.user.is_authenticated:
        if not request.user.first_name or not request.user.profile.phone:
            from django.contrib import messages
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
            order.save()
            for item in cart:
                OrderItem.objects.create(
                    order=order,
                    product=item['product'],
                    price=item['price'],
                    quantity=item['quantity'],
                )
            # Очищаем корзину
            request.session['cart'] = {}
            request.session.modified = True
            # Отправляем email (тестовый вывод в консоль)
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

    return render(request, 'shop/order_create.html', {'cart': cart, 'form': form})


def register_view(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            import resend
            import random
            from django.conf import settings
            # Сохраняем данные в сессию, не создаём юзера
            request.session['reg_email'] = form.cleaned_data['email']
            request.session['reg_password'] = form.cleaned_data['password1']
            # Генерируем код
            code = str(random.randint(100000, 999999))
            request.session['reg_otp'] = code
            request.session['reg_otp_time'] = str(timezone.now())
            # Отправляем письмо
            resend.api_key = settings.RESEND_API_KEY
            try:
                resend.Emails.send({
                    'from': 'noreply@progardengreen.ru',
                    'to': [form.cleaned_data['email']],
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
    email = request.session.get('reg_email')
    if not email:
        return redirect('shop:register')

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        saved_code = request.session.get('reg_otp')
        saved_time = request.session.get('reg_otp_time')

        # Проверяем срок действия (10 минут)
        from datetime import datetime
        import pytz
        otp_time = datetime.fromisoformat(saved_time).replace(tzinfo=pytz.UTC)
        elapsed = (timezone.now() - otp_time).seconds

        if code == saved_code and elapsed < 600:
            # Создаём пользователя
            password = request.session.get('reg_password')
            base = email.split('@')[0][:30]
            username = base
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f'{base}{counter}'
                counter += 1
            user = User.objects.create_user(username=username, email=email, password=password)
            # Очищаем сессию
            for key in ['reg_email', 'reg_password', 'reg_otp', 'reg_otp_time']:
                request.session.pop(key, None)
            login(request, user)
            return redirect('shop:product_list')
        else:
            return render(request, 'shop/register_verify.html', {
                'error': 'Неверный или истёкший код.',
                'email': email,
            })

    return render(request, 'shop/register_verify.html', {'email': email})


def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        try:
            user_obj = User.objects.get(email=email)
            user = authenticate(request, username=user_obj.username, password=password)
            if user is not None:
                # Генерируем OTP
                from django.conf import settings
                import resend
                import random
                from .models import OTPCode
                code = str(random.randint(100000, 999999))
                OTPCode.objects.create(user=user, code=code)
                request.session['otp_user_id'] = user.id
                # Отправляем письмо
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
                return render(request, 'shop/login.html', {'error': 'Неверный пароль.'})
        except User.DoesNotExist:
            return render(request, 'shop/login.html', {'error': 'Пользователь с таким email не найден.'})
    return render(request, 'shop/login.html')


def otp_verify(request):
    user_id = request.session.get('otp_user_id')
    if not user_id:
        return redirect('shop:login')

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        from .models import OTPCode
        from django.contrib.auth.models import User
        try:
            user = User.objects.get(id=user_id)
            otp = OTPCode.objects.filter(user=user, code=code, is_used=False).last()
            if otp and otp.is_valid():
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
    orders = Order.objects.filter(user=request.user)
    return render(request, 'shop/profile.html', {'orders': orders})


@login_required(login_url='shop:login')
def favorite_add(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    Favorite.objects.get_or_create(user=request.user, product=product)
    return redirect(request.META.get('HTTP_REFERER', 'shop:product_list'))


@login_required(login_url='shop:login')
def favorite_remove(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    Favorite.objects.filter(user=request.user, product=product).delete()
    return redirect(request.META.get('HTTP_REFERER', 'shop:product_list'))


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
            request.session['coupon_id'] = coupon.id
        except Coupon.DoesNotExist:
            request.session['coupon_id'] = None
            request.session['coupon_error'] = 'Купон не найден или истёк'
    return redirect('shop:cart_detail')


def cart_update(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id)
    action = request.GET.get('action')

    product_id_str = str(product.id)
    current_qty = cart.cart.get(product_id_str, {}).get('quantity', 0)

    if action == 'increase':
        cart.add(product, quantity=current_qty + 1, update=True)
    elif action == 'decrease' and current_qty > 1:
        cart.add(product, quantity=current_qty - 1, update=True)

    return redirect('shop:cart_detail')

from django.contrib.auth import update_session_auth_hash
from .forms import ProfileForm, PasswordChangeFormCustom


@login_required(login_url='shop:login')
def profile_edit(request):
    user = request.user
    profile = user.profile

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
    else:
        form = ProfileForm(initial={
            'first_name': user.first_name,
            'phone': profile.phone,
            'email': user.email,
        }, user=user)
        password_form = PasswordChangeFormCustom(user)

        # Подсвечиваем незаполненные поля только если пользователь пришёл с оформления заказа
        missing_fields = []
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
    orders = Order.objects.filter(user=request.user)
    return render(request, 'shop/order_history.html', {'orders': orders})


def password_reset_request(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        try:
            user = User.objects.get(email=email)
            import resend
            import random
            from django.conf import settings
            code = str(random.randint(100000, 999999))
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

        from datetime import datetime
        import pytz
        otp_time = datetime.fromisoformat(saved_time).replace(tzinfo=pytz.UTC)
        elapsed = (timezone.now() - otp_time).seconds

        if code != saved_code or elapsed >= 600:
            return render(request, 'shop/password_reset_verify.html', {'error': 'Неверный или истёкший код.'})

        if new_password != new_password2:
            return render(request, 'shop/password_reset_verify.html', {'error': 'Пароли не совпадают.'})

        # Проверка надёжности пароля
        from .forms import validate_password_strength
        from django.core.exceptions import ValidationError
        try:
            validate_password_strength(new_password)
        except ValidationError as e:
            return render(request, 'shop/password_reset_verify.html', {'error': e.messages[0]})

        # Меняем пароль
        user = User.objects.get(id=user_id)
        user.set_password(new_password)
        user.save()
        # Очищаем сессию
        for key in ['reset_user_id', 'reset_code', 'reset_time']:
            request.session.pop(key, None)
        return render(request, 'shop/password_reset_done.html')

    return render(request, 'shop/password_reset_verify.html')


from django.http import JsonResponse


def product_search_suggestions(request):
    query = request.GET.get('q', '').strip()
    if len(query) < 1:
        return JsonResponse({'results': []})

    q_lower = query.lower()
    products = Product.objects.filter(available=True)
    matching = [p for p in products if p.name.lower().startswith(q_lower)][:7]

    results = [{
        'id': p.id,
        'name': p.name,
        'slug': p.slug,
        'price': str(p.price),
        'image': p.image.url if p.image else '',
        'url': f'/{p.id}/{p.slug}/',
    } for p in matching]

    return JsonResponse({'results': results})