import discord
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os
import asyncio
from datetime import datetime

# Configurar el cliente de Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client_gs = gspread.authorize(creds)

# Configurar el cliente de Google Drive
drive_service = build('drive', 'v3', credentials=creds)

# Asegúrate de reemplazar "GUILD - DEPREDADORES" con el nombre correcto de tu hoja de cálculo
spreadsheet_name = "GUILD - DEPREDADORES"
try:
    sheet = client_gs.open(spreadsheet_name).sheet1
    print(f"Hoja de cálculo '{spreadsheet_name}' encontrada y abierta correctamente.")
except gspread.SpreadsheetNotFound:
    print(f"No se pudo encontrar una hoja de cálculo con el nombre {spreadsheet_name}")
    exit(1)
except Exception as e:
    print(f"Se produjo un error al intentar abrir la hoja de cálculo: {e}")
    exit(1)

# Configurar el cliente de Discord con permisos para leer el contenido de los mensajes
intents = discord.Intents.default()
intents.message_content = True  # Habilitar el intent de contenido de mensajes
client_dc = discord.Client(intents=intents)

# Lista de preguntas
questions = [
    "PERSONAJE",
    "CLASE",
    "NIVEL",
    "ATK",
    "DEF",
    "PREC",
    "ASCENDIDO SI/NO",
    "CRECIMIENTO",
    "CODICE"
]

async def display_table(channel):
    # Obtener todos los datos de la hoja de cálculo
    all_data = sheet.get_all_values()

    # Excluir las columnas de fotos (asumiendo que son las dos últimas columnas)
    headers = all_data[0][:len(questions)] + ["ACTUALIZADO", "VALIDADO"]
    filtered_data = [row[:len(questions)] + [row[-4], row[-3]] for row in all_data[1:]]

    # Determinar el ancho máximo de cada columna
    col_widths = [max(len(str(cell)) for cell in col) for cell in zip(*[headers] + filtered_data)]

    # Formatear los datos como una tabla
    def format_row(row):
        return "| " + " | ".join(f"{cell:<{col_widths[i]}}" for i, cell in enumerate(row)) + " |"

    header = format_row(headers)
    separator = "| " + " | ".join("-" * width for width in col_widths) + " |"
    table = "\n".join([header, separator] + [format_row(row) for row in filtered_data])

    # Enviar los datos como un mensaje en Discord
    table_message = await channel.send(f"```\n{table}\n```")

    # Enviar mensaje recordatorio
    reminder_message = await channel.send("Recuerda: Si quieres actualizar o añadir un nuevo personaje, escribe: !actualizar")

    return table_message, reminder_message

async def delete_messages(channel, table_message, reminder_message):
    # Función para eliminar mensajes con control de tasa
    async for msg in channel.history(limit=100):
        if msg != table_message and msg != reminder_message:
            try:
                await msg.delete()
                await asyncio.sleep(0.5)  # Esperar para no alcanzar el límite de tasa
            except discord.errors.HTTPException as e:
                print(f'Error al eliminar el mensaje: {e}')
                await asyncio.sleep(5)  # Esperar más tiempo si se alcanza el límite de tasa

@client_dc.event
async def on_ready():
    print(f'Bot conectado como {client_dc.user}')

@client_dc.event
async def on_message(message):
    if message.author == client_dc.user:
        return

    if message.content.startswith('!actualizar'):
        user = message.author
        user_responses = []
        photo_urls = []

        def check(m):
            return m.author == user and m.channel == message.channel

        async def ask_question(question):
            question_message = await message.channel.send(question)
            response = await client_dc.wait_for('message', check=check)
            await response.delete()
            await question_message.delete()
            await asyncio.sleep(1)
            return response.content.upper()

        try:
            # Preguntar primero el nombre del personaje
            personaje = await ask_question(questions[0])
            user_responses.append(personaje)

            # Buscar el nombre del personaje en la hoja de cálculo
            cell = sheet.find(personaje)
            personaje_existe = False
            ascendido_si = False

            if cell:
                personaje_existe = True
                row_number = cell.row
                # Obtener los valores actuales de la fila
                row_values = sheet.row_values(row_number)
                ascendido_si = row_values[6].strip().upper() == "SI"

            # Realizar las preguntas restantes según las condiciones
            for i in range(1, len(questions)):
                if i == 1 and personaje_existe:
                    # Omitir la pregunta de la clase si el personaje existe
                    user_responses.append(row_values[i].upper())
                    continue
                if i == 6 and ascendido_si:
                    # Omitir la pregunta de "ASCENDIDO SI/NO" si ya es "SI"
                    user_responses.append("SI")
                    continue
                answer = await ask_question(questions[i])
                user_responses.append(answer)

            # Solicitar dos fotos
            for _ in range(2):
                await message.channel.send(f'{user.mention}, por favor, sube una foto.')
                photo_response = await client_dc.wait_for('message', check=check)
                if photo_response.attachments:
                    attachment = photo_response.attachments[0]
                    file_name = attachment.filename
                    await attachment.save(file_name)
                    file_metadata = {'name': file_name, 'parents': ['1MF-3sPt1IvJse25tYoiuVZpkyiF9HCiC']}
                    media = MediaFileUpload(file_name, mimetype=attachment.content_type)
                    file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                    photo_url = f'https://drive.google.com/file/d/{file.get("id")}/view'
                    photo_urls.append(photo_url)
                    os.remove(file_name)
                await photo_response.delete()
                await asyncio.sleep(1)

            # Añadir la fecha de actualización y el valor de validación
            current_date = datetime.now().strftime("%d/%m/%Y")
            user_responses.append(current_date)
            user_responses.append("NO")

            # Añadir las URLs de las fotos al final de las respuestas del usuario
            user_responses.extend(photo_urls)

            if personaje_existe:
                # Si el nombre ya existe, actualizar la fila correspondiente
                sheet.update(range_name=f'A{row_number}:O{row_number}', values=[user_responses])
                await message.channel.send(f'{user.mention}, tus respuestas han sido actualizadas en Google Sheets.')
            else:
                # Si el nombre no existe, agregar una nueva fila
                sheet.append_row(user_responses)
                await message.channel.send(f'{user.mention}, todas tus respuestas han sido guardadas en Google Sheets.')

            # Mostrar la tabla actualizada
            table_message, reminder_message = await display_table(message.channel)
            # Borrar mensajes antiguos
            await delete_messages(message.channel, table_message, reminder_message)

        except Exception as e:
            await message.channel.send(f'Ocurrió un error: {e}')
            print(f'Ocurrió un error: {e}')

    elif message.content.startswith('!validar'):
        try:
            personaje = message.content.split(' ', 1)[1].strip().upper()
            cell = sheet.find(personaje)
            if cell:
                row_number = cell.row
                row_values = sheet.row_values(row_number)
                row_values[-1] = "SI"  # Asumimos que "VALIDADO" es la tercera columna desde el final
                sheet.update(range_name=f'A{row_number}:O{row_number}', values=[row_values])

                await message.channel.send(f'{message.author.mention}, el personaje {personaje} ha sido validado.')

                # Mostrar la tabla actualizada
                table_message, reminder_message = await display_table(message.channel)
                # Borrar mensajes antiguos
                await delete_messages(message.channel, table_message, reminder_message)
            else:
                await message.channel.send(f'{message.author.mention}, no se encontró el personaje {personaje}.')
        except Exception as e:
            await message.channel.send(f'Ocurrió un error: {e}')
            print(f'Ocurrió un error: {e}')

# Obtener el token del bot de las variables de entorno
TOKEN = os.environ['DISCORD_TOKEN']
client_dc.run(TOKEN)
