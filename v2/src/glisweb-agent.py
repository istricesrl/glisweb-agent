## IMPORTAZIONE LIBRERIE
#

# librerie di utilità generale
import sys, os
import platform
import configparser
import logging

# librerie per data e ora
import time

# librerie per l'interfaccia grafica
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction, QMainWindow
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QWidget, QLabel, QPushButton, QVBoxLayout
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import Qt

# librerie per il multiprocessing
import threading
from multiprocessing import Process
from multiprocessing import Manager

# librerie per i timer
from PyQt5.QtCore import QTimer

# librerie per la cattura di immagini
import numpy as np
import cv2
import imutils

# librerie per la gestione dei file PDF
import img2pdf

# librerie per la gestione delle chiamate API tramite Flask
from flask import Flask, jsonify, request

## CONFIGURAZIONI GLOBALI
#

# trovo il sistema operativo
system = platform.system()

# numero di versione
versione = '0.2.1'

# lettura del file di configurazione
try:
    config = configparser.ConfigParser()
    config.read_file( open( 'config.ini' ) )
    
except FileNotFoundError:
    print('file di configurazione non trovato, esco')
    sys.exit(1)

# formato del log
logformat = '%(asctime)s [%(levelname)s] %(filename)s: %(message)s'

# configurazione del logger
logger = logging.getLogger(__name__)
logging.basicConfig(filename='agent.log', format=logformat, level=logging.INFO)

# log
logger.info(f'avvio GlisWeb agent per {config["generale"]["deploy"]} v{versione} su {system}')

# manager per la condivisione di dati tra processi
global manager, process_data
manager = Manager()
process_data = manager.dict()

# dizionario per i dati condivisi tra thread
thread_data = {}
thread_data_lock = threading.Lock()

# inizializzazione del server Flask
app_flask = Flask(__name__)

## DEFINIZIONE DELLE CLASSI
#

# classe per l'applicazione principale
class TrayApp(QMainWindow):
    open_capture_signal = pyqtSignal(str)
    
    # costruttore
    def __init__(self):
        super().__init__()
        self.open_capture_signal.connect(self.open_capture_widget)

        # creo l'icona per il system tray
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("icon.png"))

        # Mostra la notifica di avvio
        QTimer.singleShot(500, lambda: self.show_system_notification("GlisWeb agent", "avviato"))
        
        # creo il menu contestuale
        self.create_tray_menu()

        # imposto l'avvio minimizzato
        self.tray_icon.show()
        self.hide()

    # metodo per creare il menu contestuale
    def create_tray_menu(self):

        # creo il menu contestuale
        tray_menu = QMenu()

        # aggiungo la voce "apri"
        show_action = QAction("apri", self)
        show_action.triggered.connect(self.show)
        tray_menu.addAction(show_action)

        # aggiungo la voce "esci"
        exit_action = QAction("esci", self)
        exit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(exit_action)

        # assegno il menu all'icona del system tray
        self.tray_icon.setContextMenu(tray_menu)

    # funzione per le notifiche di sistema
    def show_system_notification(self, title, message):

        # mostro la notifica
        self.tray_icon.showMessage( title, message, QSystemTrayIcon.Information, 3000 )

    # funzione per aprire la finestra di acquisizione immagini
    def open_capture_widget(self, process_id):
        self.capture_widget = CaptureWidget(process_id)
        self.capture_widget.show()

# classe per la finestra di acquisizione immagini
class CaptureWidget(QWidget):
    def __init__(self, process_id):
        super().__init__()
        self.process_id = process_id
        self.setWindowTitle('Acquisizione Immagini')

        # Imposta le dimensioni della finestra
        self.setFixedSize(800, 600)

        # Crea un QLabel per mostrare l'immagine
        self.image_label = QLabel(self)
        self.image_label.setFixedSize(640, 480)  # Imposta la dimensione del QLabel

        self.capture_button = QPushButton('Scatta Foto')
        self.finish_button = QPushButton('Termina')
        
        layout = QVBoxLayout()
        layout.addWidget(self.image_label)
        layout.addWidget(self.capture_button)
        layout.addWidget(self.finish_button)
        self.setLayout(layout)
        
        self.capture_button.clicked.connect(self.capture_image)
        self.finish_button.clicked.connect(self.finish_capture)
        
        self.image_names = []
        self.page_count = 0
        
        self.video_thread = VideoThread()
        self.video_thread.change_pixmap_signal.connect(self.update_image)
        self.video_thread.start()
        
    def update_image(self, cv_img):
        """Aggiorna l'immagine nella label."""
        qt_img = self.convert_cv_qt(cv_img)
        self.image_label.setPixmap(qt_img)
        self.current_frame = cv_img

    def convert_cv_qt(self, cv_img):
        """Converte un'immagine OpenCV in QPixmap per la visualizzazione."""
        rgb_image = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
        scaled_qt_image = qt_image.scaled(self.image_label.width(), self.image_label.height(), aspectRatioMode=Qt.KeepAspectRatio)
        return QPixmap.fromImage(scaled_qt_image)
    
    def capture_image(self):
        """Cattura l'immagine corrente."""
        self.page_count += 1
        processed_image = process_image(self.current_frame)
        image_name = f'page_{self.process_id}_{self.page_count}.jpg'
        image_path = os.path.join('tmp', image_name)
        cv2.imwrite(image_path, processed_image)
        self.image_names.append(image_name)
        with thread_data_lock:
            thread_data[self.process_id]['image_names'].append(image_name)
            thread_data[self.process_id]['last_captured'] = image_name
        logger.info(f'Immagine {image_name} salvata')
        
    def finish_capture(self):
        """Termina l'acquisizione e genera il PDF."""
        if self.page_count > 0:
            document_name = f'document_{self.process_id}.pdf'
            pdf_path = os.path.join('tmp', document_name)
            with open(pdf_path, "wb") as f:
                f.write(img2pdf.convert([os.path.join('tmp', img_name) for img_name in self.image_names]))
            with thread_data_lock:
                thread_data[self.process_id]['status'] = 'completed'
                thread_data[self.process_id]['document_name'] = document_name
            logger.info(f'PDF generato: {pdf_path}')
        else:
            with thread_data_lock:
                thread_data[self.process_id]['status'] = 'no_pages_captured'
            logger.info('nessuna pagina acquisita')
        self.video_thread.stop()
        self.close()

# classe per il thread di acquisizione video
class VideoThread(QThread):
    change_pixmap_signal = pyqtSignal(np.ndarray)
    
    def run(self):
        # Inizializza la webcam
        self._run_flag = True
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        while self._run_flag:
            ret, cv_img = cap.read()
            if ret:
                self.change_pixmap_signal.emit(cv_img)
        cap.release()
        
    def stop(self):
        self._run_flag = False
        self.wait()

## FUNZIONI PER I JOB DI TEST
#

def test_job(process_id):

    process_data[process_id]['elapsed'] = 0
    
    process_data[process_id]['status'] = 'started'

    for i in range(30):

        process_data[process_id]['elapsed'] += 1

        logger.info(f'avanzamento mock-up (PID: {process_id}): {process_data[process_id]["elapsed"]}')

        time.sleep(1)

    process_data[process_id]['status'] = 'completed'
    process_data[process_id]['image_name'] = 'prova.jpg'

    logger.info(f'PID: {process_id} status: {process_data[process_id]["status"]}')
    logger.info(f'PID: {process_id} image_name: {process_data[process_id]["image_name"]}')

## FUNZIONI PER LA CATTURA LOCALE DI IMMAGINI E DOCUMENTI
#

# funzione per la creazione di un PDF da una serie di immagini
def capture_image(process_id):

    try:

        # aggiorno i dati del thread
        with thread_data_lock:
            thread_data[process_id]['status'] = 'working'
            thread_data[process_id]['image_names'] = []
            thread_data[process_id]['error'] = []

        logger.info('inizializzo la webcam')

        # inizializzo la webcam
        cap = cv2.VideoCapture(0)

        # verifico se la webcam è stata aperta correttamente
        if not cap.isOpened():

            # aggiorno i dati del thread
            with thread_data_lock:
                thread_data[process_id]['status'] = 'error'
                thread_data[process_id]['error'].append( 'impossibile aprire la webcam' )

            logger.info('impossibile inizializzare la webcam')

            return

        else:

            logger.info('webcam inizializzata correttamente')

        page_count = 0
        image_names = []

        while True:

            # leggo un frame dalla webcam
            ret, frame = cap.read()

            if not ret:

                with thread_data_lock:
                    thread_data[process_id]['status'] = 'error'
                    thread_data[process_id]['error'].append( "errore durante l'acquisizione dell'immagine" )

                logger.info('errore durante l\'acquisizione dell\'immagine')

                break

            else:
                logger.info('immagine acquisita correttamente')

            # mostro il frame in una finestra
            cv2.imshow('premi SPAZIO per scattare una foto, Q per terminare', frame)

            # attendo la pressione di un tasto per 1ms
            key = cv2.waitKey(1) & 0xFF

            # se viene premuta la barra spaziatrice
            if key == ord(' '):

                page_count += 1

                # elaborazione dell'immagine
                processed_image = process_image(frame)
                image_name = f'page_{process_id}_{page_count}.jpg'
                image_path = os.path.join('tmp', image_name)
                cv2.imwrite(image_path, processed_image)
                image_names.append(image_path)
                logger.info(f'Immagine {image_name} salvata')

                with thread_data_lock:
                    thread_data[process_id]['image_names'].append(image_name)
                    thread_data[process_id]['last_captured'] = image_name

                logger.info('acquisita pagina %d' % page_count)

            # se viene premuto il tasto 'q'
            elif key == ord('q'):

                logger.info('fine acquisizione immagini')

                break

        # Rilascia la risorsa della webcam e chiudi le finestre
        cap.release()
        cv2.destroyAllWindows()

        # se c'è almeno una pagina acquisita
        if page_count > 0:

            # genero il PDF
            document_name = f'document_{process_id}.pdf'
            pdf_path = os.path.join('tmp', document_name)
            with open(pdf_path, "wb") as f:
                f.write(img2pdf.convert([os.path.join('tmp', img_name) for img_name in image_names]))

            with thread_data_lock:
                thread_data[process_id]['status'] = 'completed'
                thread_data[process_id]['document_name'] = document_name

            logger.info(f'PDF generato: {pdf_path}')

        else:

            with thread_data_lock:
                thread_data[process_id]['status'] = 'no_pages_captured'

            logger.info('nessuna pagina acquisita')

    except Exception as e:

        with thread_data_lock:
            thread_data[process_id]['status'] = 'error'
            thread_data[process_id]['error'].append( str(e) )

        logger.info(f'exception: {e}')

# Funzione per trasformare un'immagine in una vista dall'alto
def process_image(image):
    try:
        # Ridimensiona l'immagine per velocizzare l'elaborazione
        image_resized = imutils.resize(image, width=800)
        ratio = image.shape[1] / float(image_resized.shape[1])

        # Converti l'immagine in scala di grigi
        gray = cv2.cvtColor(image_resized, cv2.COLOR_BGR2GRAY)
        logger.info('Immagine convertita in scala di grigi')

        # Applica un filtro per ridurre il rumore
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        logger.info('Filtro Gaussiano applicato')

        # Applica la soglia per ottenere un'immagine binaria
        edged = cv2.Canny(gray, 50, 150)
        logger.info('Determinati i bordi con Canny')

        # Visualizza l'immagine dei bordi per il debug
        cv2.imshow('Edged', edged)
        cv2.waitKey(0)
        cv2.destroyAllWindows()

        # Trova i contorni nell'immagine
        contours, _ = cv2.findContours(edged.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        logger.info(f'Numero di contorni trovati: {len(contours)}')

        # Ordina i contorni per area, dal più grande al più piccolo
        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]

        doc_cnt = None
        for c in contours:
            # Approssima il contorno
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            logger.info(f'Approssimazione contorno con {len(approx)} punti')

            # Se il contorno approssimato ha quattro punti, presumiamo che sia il documento
            if len(approx) == 4:
                doc_cnt = approx
                logger.info('Contorno del documento trovato')
                break

        if doc_cnt is None:
            # Se non troviamo un contorno con 4 punti, ritorniamo l'immagine originale
            logger.info('Contorno del documento non trovato, ritorno immagine originale')
            return image

        # Applica una trasformazione prospettica per ottenere una vista dall'alto
        warped = four_point_transform(image, doc_cnt.reshape(4, 2) * ratio)
        logger.info('Trasformazione prospettica applicata')

        # Migliora il contrasto e la leggibilità
        warped_gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
        warped_gray = cv2.adaptiveThreshold(warped_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                            cv2.THRESH_BINARY, 11, 2)
        logger.info('Soglia adattiva applicata')

        # Ritorna l'immagine elaborata
        return warped_gray

    except Exception as e:
        logger.info(f'Errore durante l\'elaborazione dell\'immagine: {e}')
        return image  # Ritorna l'immagine originale in caso di errore
    
# Funzione per ordinare i punti in senso orario
def four_point_transform(image, pts):

    # Ottieni una consistenza nei tipi di dati
    rect = order_points(pts)
    (tl, tr, br, bl) = rect

    # Calcola la larghezza massima dell'immagine trasformata
    widthA = np.linalg.norm(br - bl)
    widthB = np.linalg.norm(tr - tl)
    maxWidth = max(int(widthA), int(widthB))

    # Calcola l'altezza massima dell'immagine trasformata
    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxHeight = max(int(heightA), int(heightB))

    # Costruisci l'insieme di punti per la trasformazione
    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]], dtype="float32")

    # Calcola la matrice di trasformazione prospettica
    M = cv2.getPerspectiveTransform(rect, dst)

    # Applica la trasformazione prospettica
    warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))

    return warped

# Funzione per ordinare i punti in senso orario
def order_points(pts):

    # Inizializza un array di output
    rect = np.zeros((4, 2), dtype="float32")

    # La somma dei punti (top-left avrà la somma minima, bottom-right massima)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]

    # La differenza dei punti (top-right avrà la differenza minima, bottom-left massima)
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]

    return rect

## FUNZIONI PER LA COMUNICAZIONE CON I MODULA
#

## FUNZIONI PER IL SERVER FLASK
#

# funzione per l'avvio del server Flask
def run_flask():

    # log
    logger.info('avviato il server Flask')

    # avvio del server Flask
    app_flask.run(port=5000)

# route per il preflight CORS
@app_flask.after_request
def after_request(risposta):

    # log
    logger.info('richiesta CORS')

    # header HTTP da restituire
    risposta.headers.add('Access-Control-Allow-Origin', '*')
    risposta.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    risposta.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')

    # restituisco la risposta
    return risposta

# route di test (echo server)
@app_flask.route('/echo', methods=['POST'])
def api_echo():

    # log
    logger.info('richiesta POST/echo ricevuta')

    # ricezione del JSON
    dati = request.get_json()

    # preparo la risposta
    risposta = { 'status': 'OK', 'info': [], 'errori': [] }

    # unisco i dati alla risposta
    risposta['info'].append(dati)
    
    # restituisco la risposta
    return jsonify(risposta)

# route per la gestione dell'avvio di un job di esempio
@app_flask.route('/testjobstart', methods=['POST'])
def api_test_job_start():

    # log
    logger.info('richiesta di avvio di un job di test')

    # ricezione del JSON
    dati = request.get_json()

    # aggiungo il comando ricevuto alla risposta
    risposta = { 'status': '', 'info': [], 'errori': [] }

    # verifico che che la voce comando esista in dati
    if 'comando' in dati:

        # log
        logger.info(f'comando ricevuto: {dati["comando"]}')

        # creazione ID del processo
        process_id = str(int(time.time()))

        process_data[process_id] = manager.dict()

        process_data[process_id]['status'] = 'created'
        process_data[process_id]['document_name'] = None
        process_data[process_id]['error'] = None

        # avvio il sottoprocesso per l'acquisizione dell'immagine
        p = Process(target=test_job, args=(process_id,))
        p.start()

        # rispondo al client con l'ID del processo
        risposta['status'] = 'OK'
        risposta['process_id'] = process_id
        risposta['info'].append( 'job di test avviato' )

    else:

        # log
        logger.info('comando non presente nel JSON')

        # aggiungo l'errore agli errori della risposta
        risposta['errori'].append( 'comando non presente nel JSON' )

    # restituisco la risposta in formato JSON
    return jsonify(risposta)

# route per la lettura dello stato di un job di esempio
# TODO convertire in modo che lavori con GET
@app_flask.route('/testjobstatus', methods=['POST'])
def api_test_job_status():

    # ricevo il process_id dal client
    dati = request.get_json()
    process_id = dati.get('process_id')

    # risposta
    risposta = {'status': '', 'document_name': None, 'error': None}

    # verifico se il process_id è valido
    if process_id in process_data:
        risposta['status'] = process_data[process_id]['status']

        if 'elapsed' in process_data[process_id]:
            risposta['elapsed'] = process_data[process_id]['elapsed']
        else:
            risposta['elapsed'] = 'n/a'

        if process_data[process_id]['status'] == 'completed':
            risposta['document_name'] = process_data[process_id]['document_name']
        elif process_data[process_id]['status'] == 'error':
            risposta['error'] = process_data[process_id]['error']

    else:
        risposta['status'] = 'KO'
        risposta['error'] = f'ID processo {process_id} non valido'

    return jsonify(risposta)

# route di test per l'apertura di una finestra dell'applicazione
@app_flask.route('/testopenwindow', methods=['POST'])
def api_test_open_window():
    
    # log
    logger.info('richiesta POST/testopenwindow ricevuta')

    # apro la finestra dell'applicazione
    window.show()

    # preparo la risposta
    risposta = { 'status': 'OK', 'info': [], 'errori': [] }

    # restituisco la risposta
    return jsonify(risposta)

# route per la cattura di un documento tramite webcam
@app_flask.route('/getwebcamdoc', methods=['POST'])
def get_webcam_document():

    # log
    logger.info('richiesta di acquisizione immagine da webcam ricevuta')

    # creo un ID univoco per il processo
    process_id = str(int(time.time()))

    # aggiungo il processo al dizionario
    with thread_data_lock:
        thread_data[process_id] = {'status': 'in_progress', 'image_names': [], 'error': []}

    # emetto il segnale per aprire il widget
    window.open_capture_signal.emit(process_id)

    # preparo la risposta
    risposta = { 'status': 'OK', 'process_id': process_id, 'info': [], 'errori': [] }

    # informazioni
    risposta['info'].append('avviata acquisizione immagine da webcam')

    # restituisco l'ID del processo al client
    return jsonify(risposta)

# route per la cattura di un documento tramite webcam
@app_flask.route('/getwebcamdocname', methods=['POST'])
def get_webcam_document_name():

    # ricevo l'ID processo dal client
    dati = request.get_json()
    process_id = dati.get('process_id')

    # preparo la risposta
    risposta = { 'status': 'OK', 'image_name': None, 'document_name': None, 'info': [], 'errori': [] }

    # verifico se l'ID processo esiste
    if process_id in thread_data:

        # inserisco le informazioni nella risposta
        risposta['status'] = thread_data[process_id]['status']
        if thread_data[process_id]['status'] == 'completed':
            risposta['document_name'] = thread_data[process_id]['document_name']
        elif thread_data[process_id]['status'] == 'error':
            risposta['error'] = thread_data[process_id]['error']
        elif thread_data[process_id]['status'] == 'started':
            risposta['last_captured'] = thread_data[process_id].get('last_captured', None)

    else:
        risposta['status'] = 'process_not_found'
        risposta['error'].append( f'ID processo {process_id} non valido' )

    # restituisco la risposta al client
    return jsonify(risposta)

## PROGRAMMA PRINCIPALE
#

# esecuzione del programma
if __name__ == "__main__":

    # log
    logger.info(f'avvio processo principale (PID: %d)' % os.getpid())

    # vado in modalità silenziosa
    if system == "Linux":
        sys.stdout = open("run.log", "w")
        sys.stderr = open("run.log", "w")

    # avvio il server Flask in un thread separato
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # creo l'applicazione
    app = QApplication(sys.argv)

    # inibisco la chiusura dell'applicazione quando si chiude l'ultima finestra
    app.setQuitOnLastWindowClosed(False)

    # avvio l'applicazione principale
    window = TrayApp()

    # eseguo l'applicazione
    sys.exit(app.exec_())
