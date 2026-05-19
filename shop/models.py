import hashlib

from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.crypto import constant_time_compare


class Category(models.Model):
    name = models.CharField(max_length=200, verbose_name='Название')
    slug = models.SlugField(max_length=200, unique=True)

    class Meta:
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='products',
        verbose_name='Категория',
    )
    name = models.CharField(max_length=200, verbose_name='Название')
    slug = models.SlugField(max_length=200, unique=True)
    image = models.ImageField(upload_to='products/', blank=True, verbose_name='Фото')
    description = models.TextField(blank=True, verbose_name='Описание')
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Цена')
    available = models.BooleanField(default=True, verbose_name='В наличии')
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товары'
        ordering = ['name']
        indexes = [
            models.Index(fields=['available', 'category']),
        ]

    def __str__(self):
        return self.name


class Order(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, verbose_name='Покупатель',
                             related_name='orders')
    first_name = models.CharField(max_length=100, blank=True, verbose_name='Имя')
    last_name = models.CharField(max_length=100, blank=True, verbose_name='Фамилия')
    phone = models.CharField(max_length=20, blank=True, verbose_name='Телефон')
    PICKUP_POINTS = [
        ('Респ. Башкортостан, г. Уфа, ул. Зелёная, д. 12', 'ул. Зелёная, д. 12'),
        ('Респ. Башкортостан, г. Уфа, ул. Садовая, д. 47', 'ул. Садовая, д. 47'),
        ('Респ. Башкортостан, г. Уфа, ул. Лесная, д. 3', 'ул. Лесная, д. 3'),
        ('Респ. Башкортостан, г. Уфа, пр-т Октября, д. 118', 'пр-т Октября, д. 118'),
        ('Респ. Башкортостан, г. Уфа, ул. Цветочная, д. 29', 'ул. Цветочная, д. 29'),
        ('Респ. Башкортостан, г. Уфа, ул. Рябиновая, д. 6', 'ул. Рябиновая, д. 6'),
        ('Респ. Башкортостан, г. Уфа, ул. Питомниковая, д. 1', 'ул. Питомниковая, д. 1'),
        ('Респ. Башкортостан, г. Уфа, ул. Берёзовая, д. 84', 'ул. Берёзовая, д. 84'),
        ('Респ. Башкортостан, г. Уфа, ул. Плодовая, д. 17', 'ул. Плодовая, д. 17'),
        ('Респ. Башкортостан, г. Уфа, пр-т Салавата Юлаева, д. 55', 'пр-т Салавата Юлаева, д. 55'),
        ('Респ. Башкортостан, г. Уфа, ул. Российская, д. 202', 'ул. Российская, д. 202'),
        ('Респ. Башкортостан, г. Уфа, ул. Комсомольская, д. 33', 'ул. Комсомольская, д. 33'),
        ('Респ. Башкортостан, г. Уфа, ул. Загородная, д. 9', 'ул. Загородная, д. 9'),
        ('Респ. Башкортостан, г. Уфа, ул. Дачная, д. 71', 'ул. Дачная, д. 71'),
        ('Респ. Башкортостан, г. Уфа, ул. Нур-Садовая, д. 5', 'ул. Нур-Садовая, д. 5'),
    ]
    address = models.CharField(max_length=255, choices=PICKUP_POINTS, verbose_name='Точка самовывоза')
    comment = models.TextField(blank=True, null=True, verbose_name='Комментарий к заказу')
    PAYMENT_CHOICES = [
        ('cash', 'Наличными при получении'),
        ('card', 'Картой при получении'),
    ]
    payment_method = models.CharField(max_length=10, choices=PAYMENT_CHOICES, verbose_name='Способ оплаты')
    created = models.DateTimeField(auto_now_add=True, verbose_name='Создан')
    paid = models.BooleanField(default=False, verbose_name='Оплачен')
    coupon = models.ForeignKey(
        'Coupon',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name='Купон',
    )
    discount = models.PositiveIntegerField(default=0, verbose_name='Скидка (%)')

    class Meta:
        verbose_name = 'Заказ'
        verbose_name_plural = 'Заказы'
        ordering = ['-created']

    def __str__(self):
        return f'Заказ №{self.id}'

    def get_total_cost(self):
        from decimal import Decimal
        total = sum(item.get_cost() for item in self.items.all())
        if self.discount:
            total = total * (1 - Decimal(self.discount) / 100)
        return total

    def get_total_cost_before_discount(self):
        return sum(item.get_cost() for item in self.items.all())

    def get_discount_amount(self):
        from decimal import Decimal
        if self.discount:
            total = sum(item.get_cost() for item in self.items.all())
            return total * Decimal(self.discount) / 100
        return Decimal('0')

    def get_order_code(self):
        return f'ORD-{self.created.year}-{self.id:04d}'


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, verbose_name='Товар')
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Цена')
    quantity = models.PositiveIntegerField(default=1, verbose_name='Количество')

    def __str__(self):
        return f'{self.product.name} x {self.quantity}'

    def get_cost(self):
        return self.price * self.quantity


class Favorite(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorites')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='favorited_by')
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Избранное'
        verbose_name_plural = 'Избранное'
        unique_together = ('user', 'product')

    def __str__(self):
        return f'{self.user.username} → {self.product.name}'


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='Автор')
    text = models.TextField(verbose_name='Отзыв')
    rating = models.PositiveIntegerField(verbose_name='Оценка', choices=[(i, str(i)) for i in range(1, 6)])
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Отзыв'
        verbose_name_plural = 'Отзывы'
        ordering = ['-created']
        unique_together = ('product', 'user')

    def __str__(self):
        return f'{self.user.username} — {self.product.name} ({self.rating}★)'


class Coupon(models.Model):
    code = models.CharField(max_length=50, unique=True, verbose_name='Код')
    discount = models.PositiveIntegerField(verbose_name='Скидка (%)')
    active = models.BooleanField(default=True, verbose_name='Активен')
    valid_from = models.DateTimeField(verbose_name='Действует с')
    valid_to = models.DateTimeField(verbose_name='Действует до')

    class Meta:
        verbose_name = 'Купон'
        verbose_name_plural = 'Купоны'

    def __str__(self):
        return f'{self.code} (−{self.discount}%)'


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone = models.CharField(max_length=20, blank=True, verbose_name='Телефон')

    def __str__(self):
        return f'Профиль {self.user.username}'


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)


class OTPCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    code_hash = models.CharField(max_length=64)
    created = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'is_used', 'created'], name='shop_otpcod_user_id_795f14_idx'),
        ]

    @staticmethod
    def hash_code(code: str) -> str:
        return hashlib.sha256(code.encode()).hexdigest()

    def check_code(self, code: str) -> bool:
        return constant_time_compare(self.code_hash, self.hash_code(code))

    def is_valid(self):
        from django.utils import timezone
        return not self.is_used and (timezone.now() - self.created).total_seconds() < 600

    def __str__(self):
        return f'OTP для {self.user.email}'