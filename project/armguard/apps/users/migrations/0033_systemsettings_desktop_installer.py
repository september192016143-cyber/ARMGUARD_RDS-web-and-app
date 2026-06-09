from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0032_simulationrun'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsettings',
            name='desktop_installer',
            field=models.FileField(
                blank=True,
                null=True,
                upload_to='desktop_installer/',
                help_text=(
                    'Upload ARMGUARD_RDS_Setup.exe here. When present, the Download button '
                    'returns a ZIP containing both the installer and the pre-configured .env '
                    'so users only need to extract and run Setup.exe.'
                ),
            ),
        ),
    ]
