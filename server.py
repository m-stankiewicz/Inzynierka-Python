import logging
import asyncio
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import openai
from aiohttp import ClientSession
import nest_asyncio

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = ''
OPENAI_API_KEY = ''

api_data_cache = {
    'vat_rates': [],
    'invoice_series': [],
    'customers': []
}

openai.api_key = OPENAI_API_KEY

async def execute_api_call(api_instruction, session):
    base_url = "http://127.0.0.1:8000/api"
    url = f"{base_url}{api_instruction['endpoint']}"
    method = api_instruction['method'].upper()
    headers = {"Content-Type": "application/json"}  # Adjust according to your API

    async with session.request(method=method, url=url, json=api_instruction.get('data', {}), headers=headers) as response:
        if response.status == 200 or response.status == 201:
            return await response.json()
        else:
            return {"error": "API call failed", "status": response.status}

async def fetch_initial_api_data(session):
    endpoints = [
        ('/vat-rates', 'vat_rates'),
        ('/invoice-series', 'invoice_series'),
        ('/customers', 'customers')
    ]
    for endpoint, key in endpoints:
        response = await execute_api_call({'method': 'GET', 'endpoint': endpoint, 'data': None}, session)
        api_data_cache[key] = response

async def handle_message(update: Update, context):
    user_message = update.message.text
    async with ClientSession() as session:
        await fetch_initial_api_data(session)
        vat_rates_info = json.dumps(api_data_cache['vat_rates'], indent=2)
        invoice_series_info = json.dumps(api_data_cache['invoice_series'], indent=2)
        customers_info = json.dumps(api_data_cache['customers'], indent=2)

    

    instructions_json = await query_llm_for_instructions(user_message, vat_rates_info, invoice_series_info, customers_info)
    if not instructions_json:
        response_message = "Sorry, I encountered a problem processing your request."
    else:
        # Assuming instructions_json is an actionable dict for an API call
        async with ClientSession() as session:
            api_response = await execute_api_call(instructions_json, session)
            response_message = json.dumps(api_response, indent=2)
            response = openai.ChatCompletion.create(
        model="gpt-4-0125-preview", 
        messages=[{"role": "system", "content": "Jesteś stworzony do odpowiadania na wstępny prompt użytkownika na podstawie odpowiedzi z api."},
                {"role": "user", "content": "Wiadomość użytkownika to: "+user_message+" Wiadomość z API to: "+response_message}],
        )
        final_response_message = response.choices[0].message.content

    await context.bot.send_message(chat_id=update.effective_chat.id, text=final_response_message)


async def query_llm_for_instructions(prompt, vat_rates_info, invoice_series_info, customers_info):
    response = openai.ChatCompletion.create(
        model="gpt-4-0125-preview", 
        messages=[{"role": "system", "content": """
                        Twoim zadaniem, jest generowanie jsona w najczystszej postaci - NIE W MARKDOWN TYLKO W PLAINTEXT I BEZ KOMENTARZY - zawierającego:
                        endpoint: wybrany endpoint na żądanie użytkownika
                        data: tu wszelkie informacje dotyczące tego żądania

                        Przykładowy json dla nowej faktury
                        W celu wyszukiwania konkretnego customera przeszukaj bloki json i przekaż id należące do pasującego bloku json
                        {
                            "method": "POST",
                            "endpoint": "/store-invoice",
                            "data": {
                                "customer_id": "1", //tutaj ID customera - w prompcie od użytkownika masz listę wszystkich klientów
                                "invoice_series_id": "1", //tutaj ID serii. Jeżeli jest jedna, wtedy wstaw do tego konkretnego
                                "invoiceItems": [ //wymagany conajmniej 1
                                {
                                    "name": "Produkt A", //nazwa usługi/produktu
                                    "unit": "szt.", //tutaj jaka jednostka miary
                                    "unit_price": 100, //cena netto
                                    "vat_rate_id": "1", // tutaj ID do encji ze stawką vat
                                    "quantity": 2, // tutaj liczba
                                    "description": "" //tutaj opis
                                }
                                ],
                                "description": "opis" // może być pusty string
                                "issue_date": "2023-01-01", //data wstawienia
                                "payment_received_date": null, //data płatności - możliwy null
                            }
                        }
                   
                   
                        Przykładowy json dla nowego customera
                        {
                            "method": "POST",
                            "endpoint": "/store-customer",
                            "data": {
                                "name": "Nazwa firmy",
                                "address": "Adres firmy",
                                "vat_id": "Nip firmy", //tu może być null jeśli nie podany
                                "email": "email", //tu może być null jeśli nie podany
                                "phone": "214124451421", //numer telefonu - tu może być null jeśli nie podany
                                "is_company": true, //jeśli firma to true, jeśli osoba fizyczna to false
                            }
                        }
                   
                        Jeżeli coś nie pasuje
                        {
                            "error": "wiadomość reprezentująca to, co chcesz przekazać"
                        }
                   
                        Oto dane, które zawiera system
                        VAT Rates: """+vat_rates_info+"""
                        Invoice Series: """+invoice_series_info+"""
                        Customers: """+customers_info
                        },
                  {"role": "user", "content": prompt}],
    )


    try:
        instructions = json.loads(response.choices[0].message.content)
        return instructions
    except json.JSONDecodeError:
        logger.error("Failed to decode JSON from LLM response.")
        return None

async def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", handle_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await application.run_polling()

if __name__ == '__main__':
    nest_asyncio.apply()
    asyncio.run(main())
