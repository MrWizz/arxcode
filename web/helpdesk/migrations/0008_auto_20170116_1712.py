# -*- coding: utf-8 -*-
# Generated by Django 1.9.9 on 2017-01-16 17:12
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('helpdesk', '0007_ticket_submitting_room'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ticket',
            name='priority',
            field=models.IntegerField(blank=3, choices=[(1, '1. Critical'), (2, '2. High'), (3, '3. Normal'), (4, '4. Low'), (5, '5. Very Low'), (6, '6. Super Low')], default=3, help_text='1 = Highest Priority, 5 = Low Priority', verbose_name='Priority'),
        ),
        migrations.AlterField(
            model_name='ticket',
            name='submitting_room',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='objects.ObjectDB', verbose_name='Room where this was submitted'),
        ),
    ]
