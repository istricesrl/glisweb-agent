#!/usr/bin/python3

## AGENT PYTHON PER IL FRAMEWORK GLISWEB
#
# compilazione con PyInstaller
# ----------------------------
# python.exe -m PyInstaller --onefile --hidden-import plyer.platforms.win.notification -w agent11.py
# python.exe -m PyInstaller --onefile --noconsole --hidden-import plyer.platforms.win.notification -w agent11.py
#
# installazione delle librerie
# ----------------------------
# pip install flask plyer pystray pillow olefile pywin32 python-daemon pyinstaller notification
#
# esempi di file config.ini
# -------------------------
#
# [modula]
# host = 192.168.1.91
# porta = 11001
#

## IMPORTAZIONE LIBRERIE
#

# librerie di utilità generale
import configparser
import logging
import os
import platform
import sys

# librerie per il multiprocessing
import multiprocessing
from multiprocessing import Process

# librerie per il server Flask
from flask import Flask, request, jsonify

# librerie per l'icona di sistema
from PIL import Image
from plyer import notification
import pystray
from pystray import Icon, MenuItem

# librerie per data e ora
import time

# librerie per la comunicazione
import socket

# trovo il sistema operativo
system = platform.system()

# inclusioni specifiche per il sistema operativo
if system == "Linux":
    from daemon import DaemonContext

## CONFIGURAZIONE GENERALE
#

# numero di versione
versione = '0.1.7'

# lettura del file di configurazione
config = configparser.ConfigParser()
config.read_file( open( 'config.ini' ) )

# formato del log
logformat = '%(asctime)s [%(levelname)s] %(filename)s: %(message)s'

# configurazione del logger
logger = logging.getLogger(__name__)
logging.basicConfig(filename='agent.log', encoding='utf-8', format=logformat, level=logging.INFO)

# log
logger.info(f'avvio GlisWeb agent v{versione} su {system}')

# lista dei processi
processi = []

## FUNZIONI PER IL SERVER FLASK
#

# funzione per il parsing dei comandi Modula
def parse_modula( comando ):

    # esplodo il comando per | e ritorno un array
    cmdinfo = comando.split('|')

    # eseguo il trim di ogni elemento dell'array
    cmdinfo = [ x.strip() for x in cmdinfo ]

    return cmdinfo

# funzione per l'invio dei comandi Modula
def send_command( comando ):

    logger.info(F'invio del comando: {comando}')

    host = config["modula"]["host"]
    porta = int(config["modula"]["porta"])
    buf_size = 30

    try:

        logger.info('creazione socket...')
        s = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        logger.info('socket creato con successo')

        logger.info(f'connessione alla porta {porta}')
        s.connect((host,porta))
        logger.info(f'socket connesso correttamente alla porta {porta}')

        logger.info(f'codifico in UTF-8 il comando {comando}')
        msg = comando.encode('utf-8') + b'\r'

        logger.info(f'invio i dati al server {host}:{porta}')
        s.send(msg)
        logger.info(f'comando {comando} inviato correttamente al server {host}:{porta}')

        logger.info('ricevo i dati dal server...')
        data = s.recv(buf_size)

        logger.info('decodifico i dati rivevuti...')
        data = data.decode('utf-8')

        logger.info(f'risposta ricevuta dal server: { data }')

        logger.info('disconnetto il socket...')
        s.close()
        logger.info('socket disconnesso con successo')

    except Exception as e:
            logger.error(f'errore durante l\'invio del comando: { e }')
            data = '-99'

    return parse_modula(data)

# funzione per l'invio pigro dei comandi
def lazy_call(comando):
    logger.info(f'invio pigro del comando CALL: {comando}')

    # TODO gli altri processi dovrebbero avere contezza dei comandi in coda e del numero di tentativi rimanenti

    tentativi = 0

    while True:
        time.sleep(1)
        tentativi += 1

        data = send_command(comando)

        # se data è una lista e ha almeno 4 elementi
        if isinstance(data, list) and len(data) >= 4:
            if data[3] == '0':
                logger.info('comando CALL eseguito con successo, esco dal ciclo...')
                break
            elif data[3] == '-1':
                logger.info('cassetto non valido, esco dal ciclo...')
                break
            elif data[3] == '-2':
                logger.info('piazzola non valida, esco dal ciclo...')
                break
            elif data[3] == '-5':
                logger.info('login non eseguito o piazzola non attiva, esco dal ciclo...')
                break
            elif data[3] == '-6':
                logger.info('macchina non in automatico, esco dal ciclo...')
                break
            elif tentativi >= 300:
                logger.info(f'raggiunto il limite di tentativi ({tentativi}) per il comando {comando}, esco dal ciclo...')
                notification.notify( title='GlisWeb Agent', message=f'comando {comando} scartato per timeout', timeout=5 )
                break
            else:
                logger.info(f'comando CALL non eseguito ({data[3]}), continuo il ciclo...')
        else:
            logger.error(f'errore durante l\'invio del comando CALL: {data}')
            break

    return data

# funzione per l'avvio del server Flask
def run_server():

    # log
    logger.info('avviato il server Flask (PID: %d)' % os.getpid())

    # avvio del server Flask
    app = Flask(__name__)

    # route per il preflight CORS
    @app.after_request
    def after_request(risposta):

        # log
        logger.info('richiesta CORS')

        # header HTTP da restituire
        risposta.headers.add('Access-Control-Allow-Origin', '*')
        risposta.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        risposta.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')

        # restituisco la risposta
        return risposta

    # route per la ricezione dei comandi Modula
    @app.route('/modula', methods=['POST'])
    def modula_request():

        # log
        logger.info('richiesta POST/modula ricevuta')

        # ricezione del JSON
        dati = request.get_json()

        # verifico che che la voce comando esista in dati
        if 'comando' in dati:

            # log
            logger.info('comando ricevuto: %s' % dati['comando'])

            # aggiungo il comando ricevuto alla risposta
            risposta = { 'comando': dati['comando'], 'status': '', 'risposta':'', 'info': [], 'errori': [] }

            # faccio il parsing del comando
            dettagli = parse_modula( dati['comando'] )

            # valuto se il dettagli[2] è nella lista [ 'CALL', 'RETURN', 'STATUS' ]
            if dettagli[2] in [ 'CALL', 'RETURN', 'STATUS' ]:

                # log
                logger.info(f'comando { dettagli[2] } ({ dati["comando"] }) ricevuto')

                # notifica di sistema
                notification.notify( title=f'comando { dettagli[2] } ricevuto', message=f'comando ricevuto: { dati["comando"] }', timeout=5 )

                # valuto il comando
                if dettagli[2] == 'CALL':

                    # invio il comando in modalità pigra
                    risultato = lazy_call( dati['comando'] )

                else:

                    # invio il comando in modalità attiva
                    risultato = send_command( dati['comando'] )

                # log
                logger.info(f'risultato della chiamata: { risultato }')

                # valutazione del risultato
                if risultato[0] == '-99':
                    risposta['errori'].append( 'errore durante l\'invio del comando' )
                elif risultato[2] == 'CALL' and risultato[3] == '-1':
                    risposta['errori'].append( 'cassetto non valido' )
                elif risultato[2] == 'CALL' and risultato[3] == '-2':
                    risposta['errori'].append( 'piazzola non valida' )
                elif risultato[2] == 'CALL' and risultato[3] == '-5':
                    risposta['errori'].append( 'login non effettuato o piazzola non attiva' )
                elif risultato[2] == 'CALL' and risultato[3] == '-6':
                    risposta['errori'].append( 'modalità automatica non inserita' )
                elif risultato[2] == 'RETURN' and risultato[3] == '-1':
                    risposta['errori'].append( 'piazzola vuota' )
                elif risultato[2] == 'RETURN' and risultato[3] == '-2':
                    risposta['errori'].append( 'piazzola non valida' )
                else:
                    risposta['risposta'] = 'comando eseguito'
                    risposta['status'] = 'OK'

            else:

                # log
                logger.error(f'comando non previsto { dettagli[2] } ({ dati["comando"] }) ricevuto')

                # aggiungo l'errore agli errori della risposta
                risposta['errori'].append( f'comando non previsto ricevuto: { dati["comando"] }' )

                # notifica di sistema
                notification.notify( title=f'comando { dettagli[2] } non valido ricevuto', message=f'comando ricevuto: { dati["comando"] }', timeout=5 )

        else:

            # log
            logger.error('comando non presente nel JSON')

            # aggiungo l'errore agli errori della risposta
            risposta['errori'].append( 'comando non presente nel JSON' )

        # restituisco la risposta in formato JSON
        return jsonify(risposta)

    # avvio del server Flask
    # app.run(port=5000, threaded=True)
    app.run(port=5000)

## FUNZIONI PER L'ICONA DI SISTEMA
#

# funzione per mostrare la finestra di informazioni
def show_info():

    # log
    logger.info('mostrata la finestra di informazioni')

    # messaggio
    messaggio = f'GlisWeb Agent v{versione} in esecuzione su {system} (PID: {os.getpid()}) \n\n'
    for processo in processi:
        messaggio += f'Processo: {processo.name} (PID: {processo.pid}) \n'

    # notifica di sistema
    notification.notify( title='GlisWeb Agent', message=messaggio, timeout=5 )

# funzione per l'uscita dal programma
def graceful_exit(icon):

    # log
    logger.info('uscita dal programma')

    # notifica di sistema
    notification.notify( title='GlisWeb Agent', message='Chiusura in corso...', timeout=5 )

    # chiusura dei processi
    for processo in processi:
        logger.info(f'terminazione del processo {processo.name} (PID: {processo.pid})')
        processo.terminate()

    # uscita dal programma
    icon.stop()

# funzione per l'avvio dell'icona di sistema
def run_icon():

    # log
    logger.info('avviata l\'icona di sistema (PID: %d)' % os.getpid())

    # configurazione dell'icona di sistema
    icon = Icon('GlisWeb Agent', Image.open('icon.png'), menu=pystray.Menu(
        MenuItem('informazioni', lambda: show_info(icon) ),
        MenuItem('esci', lambda: graceful_exit(icon))
    ))

    # avvio dell'icona di sistema
    icon.run()

## PROGRAMMA PRINCIPALE
#

# se mi trovo nel contesto main
if __name__ == '__main__':

    # log
    logger.info(f'avvio processo principale (PID: %d)' % os.getpid())

    # vado in modalità silenziosa
    if system == "Linux":
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")

    # notifica di sistema per l'avvio del programma
    notification.notify( title='GlisWeb Agent avviato', message=f'GlisWeb Agent v{versione} in esecuzione...', timeout=5 )

    # abilito il freeze support
    multiprocessing.freeze_support()

    # log
    logger.info(f'attivato il freeze_support()')

    # avvio del server Flask
    server_process = Process(target=run_server,name='server_process')
    server_process.start()

    # aggiungo il processo alla lista dei processi
    processi.append(server_process)

    # strategie specifiche per il sistema operativo
    if system == "Linux":

        # log
        logger.info(f'avvio per {system} PID: {os.getpid()}')

        # avvio dell'icona di sistema
        icon_process = Process(target=run_icon,name='icon_process')
        icon_process.start()

        # aggiungo il processo alla lista dei processi
        processi.append(icon_process)

        # demonizzo il processo
        with DaemonContext():
            server_process.join()
            icon_process.join()

    elif system == "Windows":

        # log
        logger.info(f'avvio per {system} PID: {os.getpid()}')

        # avvio dell'icona di sistema
        run_icon()

    else:
        
        # log
        logger.error(f'sistema operativo non supportato: {system}')

        # uscita con errore
        sys.exit(1)
