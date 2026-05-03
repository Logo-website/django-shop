def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    for field in self.fields.values():
        field.widget.attrs['class'] = 'form-control'
    self.fields['password1'].help_text = 'Мин. 8 символов, заглавная, строчная, цифра, спецсимвол.'
    self.fields['password2'].help_text = ''
    # Отключаем стандартные валидаторы Django — используем свой
    self.fields['password2'].validators = []