import re
from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Order, Review
from .models import Profile


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['address', 'comment', 'payment_method']
        widgets = {
            'address': forms.Select(attrs={'class': 'form-select'}),
            'comment': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Например: позвоните за час до доставки...'}),
            'payment_method': forms.RadioSelect(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['address'].choices = [('', 'Выберите пункт самовывоза')] + list(Order.PICKUP_POINTS)
        self.fields['payment_method'].widget.choices = Order.PAYMENT_CHOICES


def validate_password_strength(password):
    if len(password) < 8:
        raise ValidationError('Минимум 8 символов.')
    if len(password) > 128:
        raise ValidationError('Максимум 128 символов.')
    if not re.search(r'[A-Z]', password):
        raise ValidationError('Хотя бы одна заглавная буква (A-Z).')
    if not re.search(r'[a-z]', password):
        raise ValidationError('Хотя бы одна строчная буква (a-z).')
    if not re.search(r'[0-9]', password):
        raise ValidationError('Хотя бы одна цифра.')
    if not re.search(r'[!@#$%^&*(),.?":{}|<>\-_=+\[\]\\;\'`~/]', password):
        raise ValidationError('Хотя бы один спецсимвол (!@#$%^&* и т.д.).')


class RegisterForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        label='Логин',
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'example@mail.ru'}),
    )

    class Meta:
        model = User
        fields = ['email', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
        self.fields['password1'].help_text = 'Мин. 8 символов, заглавная, строчная, цифра, спецсимвол.'
        self.fields['password2'].help_text = ''
        self.fields['password2'].validators = []

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('Этот логин уже зарегистрирован.')
        return email

    def clean_password1(self):
        password = self.cleaned_data.get('password1')
        if password:
            validate_password_strength(password)
        return password

    def save(self, commit=True):
        user = super(UserCreationForm, self).save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        user.email = self.cleaned_data['email']
        base = self.cleaned_data['email'].split('@')[0][:30]
        username = base
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f'{base}{counter}'
            counter += 1
        user.username = username
        if commit:
            user.save()
        return user


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['rating', 'text']
        widgets = {
            'text': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Напишите отзыв...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['rating'].widget = forms.RadioSelect(choices=[(i, f'{i} ★') for i in range(1, 6)])
        self.fields['rating'].empty_label = None


class CouponForm(forms.Form):
    code = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Введите промокод',
        }),
        label='Промокод',
    )

class ProfileForm(forms.Form):
    first_name = forms.CharField(max_length=100, required=False, label='Имя',
                                  widget=forms.TextInput(attrs={'class': 'form-control'}))
    phone = forms.CharField(max_length=20, required=False, label='Телефон',
                             widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(required=True, label='Email',
                              widget=forms.EmailInput(attrs={'class': 'form-control'}))

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError('Этот email уже занят.')
        return email


class PasswordChangeFormCustom(forms.Form):
    old_password = forms.CharField(label='Текущий пароль',
                                    widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    new_password1 = forms.CharField(label='Новый пароль',
                                     widget=forms.PasswordInput(attrs={'class': 'form-control'}),
                                     help_text='Мин. 8 символов, заглавная, строчная, цифра, спецсимвол.')
    new_password2 = forms.CharField(label='Подтверждение пароля',
                                     widget=forms.PasswordInput(attrs={'class': 'form-control'}))

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_old_password(self):
        old = self.cleaned_data.get('old_password')
        if not self.user.check_password(old):
            raise forms.ValidationError('Неверный текущий пароль.')
        return old

    def clean_new_password1(self):
        password = self.cleaned_data.get('new_password1')
        if password:
            validate_password_strength(password)
        return password

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('new_password1')
        p2 = cleaned.get('new_password2')
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError('Пароли не совпадают.')
        return cleaned