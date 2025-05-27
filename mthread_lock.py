import hashlib
import psycopg2
from uuid import uuid4
# from datetime import datetime # Non usata direttamente in questo script modificato
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import os
import threading
import time
import random

# --- Variabili di Connessione al DB (da ENV o default) ---
db_name = os.environ.get("DB_NAME", "signature_demo")
db_user = os.environ.get("SUPER_DB_USER", "postgres")
db_password = os.environ.get("SUPER_DB_PASSWORD", "postgres")
db_host = os.environ.get("DB_HOST", "localhost")

# Lock globale per serializzare le operazioni critiche sul DB
db_operation_lock = threading.Lock()

# --- Funzioni Crittografiche (semplificate/adattate da main.py) ---
def generate_keys_for_simulation():
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048)
    pem_private = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption())
    # public_key = private_key.public_key() # Non usata in questa simulazione
    # pem_public = public_key.public_bytes(
    #     encoding=serialization.Encoding.PEM,
    #     format=serialization.PublicFormat.SubjectPublicKeyInfo)
    return pem_private, None # Restituiamo None per la chiave pubblica non usata

def sign_data_for_simulation(private_key_pem, data_to_sign):
    private_key = serialization.load_pem_private_key(
        private_key_pem, password=None)
    signature_bytes = private_key.sign(
        data_to_sign,
        padding.PKCS1v15(),
        hashes.SHA256())
    return signature_bytes.hex()

def get_document_hash(document_content):
    return hashlib.sha256(document_content.encode()).hexdigest()

# --- Funzioni di Interazione con il DB per la Simulazione ---

def clear_table(conn):
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM signature_chain;")
    conn.commit()
    print("Tabella signature_chain pulita.")

# get_last_signature_for_doc non è più usata direttamente dai thread se il lock protegge la lettura

def insert_genesis_block(conn, document_id_param, signer_name, doc_hash, signature_param):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO signature_chain (document_id, signer, document_hash, prev_hash, signature)
            VALUES (%s, %s, %s, %s, %s) RETURNING id;
            """,
            (document_id_param, signer_name, doc_hash, None, signature_param)
        )
        block_id = cursor.fetchone()[0]
    conn.commit()
    print(f"Blocco Genesi inserito per doc {document_id_param} da {signer_name}, ID: {block_id}, Signature: {signature_param[:10]}...")
    return block_id

def concurrent_insert_signature(
        document_id_param,
        signer_name,
        document_content,
        private_key_pem,
        thread_name):
    """
    Simula l'inserimento di una firma, utilizzando un lock applicativo
    per prevenire race conditions.
    """
    conn_thread = None
    try:
        conn_thread = psycopg2.connect(dbname=db_name, user=db_user, password=db_password, host=db_host)
        conn_thread.autocommit = False # Controllo manuale della transazione

        doc_hash = get_document_hash(document_content)

        # Acquisire il lock prima di accedere alla sezione critica
        # Il lock serializza l'intero blocco with
        with db_operation_lock:
            print(f"[{thread_name}] Acquisito lock per {signer_name}")
            # 1. Leggi l'ultimo prev_hash (PUNTO CRITICO)
            # Ora questa operazione è protetta dal lock applicativo
            with conn_thread.cursor() as cur_select:
                # SELECT ... FOR UPDATE non è più strettamente necessario qui,
                # poiché il lock applicativo serializza l'intera logica.
                # Potrebbe essere lasciato per una "difesa in profondità" o rimosso.
                # Per questo esempio, lo rimuoviamo per mostrare l'effetto del lock applicativo.
                cur_select.execute(
                    "SELECT signature FROM signature_chain WHERE document_id = %s ORDER BY id DESC LIMIT 1",
                    (document_id_param,)
                )
                result = cur_select.fetchone()
                prev_hash = result[0] if result else None

            print(f"[{thread_name}] Letto prev_hash: {prev_hash[:10] if prev_hash else 'NULL'} per {signer_name} (dentro il lock)")

            # 2. Simula elaborazione / ritardo di rete
            # Questo ritardo è ancora utile per vedere l'effetto del lock
            time.sleep(random.uniform(0.1, 0.3)) # Ritardo per simulazione

            # 3. Crea la firma
            data_to_sign = (prev_hash or '').encode() + doc_hash.encode()
            current_signature = sign_data_for_simulation(private_key_pem, data_to_sign)

            # 4. Inserisci il nuovo blocco (PUNTO CRITICO)
            with conn_thread.cursor() as cur_insert:
                cur_insert.execute(
                    """
                    INSERT INTO signature_chain (document_id, signer, document_hash, prev_hash, signature)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id;
                    """,
                    (document_id_param, signer_name, doc_hash, prev_hash, current_signature)
                )
                block_id = cur_insert.fetchone()[0]
            conn_thread.commit() # Commit all'interno del lock
            print(f"[{thread_name}] {signer_name} ha inserito il blocco ID: {block_id} con prev_hash: {prev_hash[:10] if prev_hash else 'NULL'}, Signature: {current_signature[:10]}... (rilascio lock)")
        # Il lock viene rilasciato automaticamente uscendo dal blocco 'with db_operation_lock'

    except (Exception, psycopg2.Error) as error:
        print(f"[{thread_name}] Errore per {signer_name}: {error}")
        if conn_thread:
            conn_thread.rollback() # Rollback in caso di errore
    finally:
        if conn_thread:
            conn_thread.close()

def check_for_forks(conn, document_id_param):
    print(f"\n--- Controllo Biforcazioni per Documento ID: {document_id_param} ---")
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT prev_hash, COUNT(*) as count
            FROM signature_chain
            WHERE document_id = %s AND prev_hash IS NOT NULL
            GROUP BY prev_hash
            HAVING COUNT(*) > 1;
            """,
            (document_id_param,)
        )
        forks = cursor.fetchall()
        if forks:
            print("!!! PROBLEMA DI CONCORRENZA RILEVATO: BIFORCAZIONE NELLA CATENA !!!")
            for fork in forks:
                print(f"  prev_hash '{fork[0]}' appare {fork[1]} volte.")
        else:
            print("Nessuna biforcazione rilevata (prev_hash duplicati non trovati). La catena è sequenziale.")

        cursor.execute("SELECT id, signer, prev_hash, signature FROM signature_chain WHERE document_id = %s ORDER BY id", (document_id_param,))
        print("\nStato finale della catena:")
        for row in cursor.fetchall():
            print(f"  ID: {row[0]}, Firmatario: {row[1]}, PrevHash: {row[2][:10] if row[2] else 'NULL'}, Signature: {row[3][:10]}...")


if __name__ == "__main__":
    main_conn = None
    try:
        main_conn = psycopg2.connect(dbname=db_name, user=db_user, password=db_password, host=db_host)
        clear_table(main_conn)

        doc_id = str(uuid4())
        document_content_main = "Contenuto del documento per test di concorrenza."
        doc_hash_main = get_document_hash(document_content_main)

        # Firmatario Genesi
        priv_key_gen, _ = generate_keys_for_simulation()
        genesis_signature = sign_data_for_simulation(priv_key_gen, doc_hash_main.encode()) # prev_hash è ''
        insert_genesis_block(main_conn, doc_id, "FirmatarioGenesi", doc_hash_main, genesis_signature)

        print("\nAvvio inserimenti concorrenti...")

        # Chiavi per i firmatari concorrenti
        priv_key_A, _ = generate_keys_for_simulation()
        priv_key_B, _ = generate_keys_for_simulation()

        # Creazione dei thread
        thread1 = threading.Thread(
            target=concurrent_insert_signature,
            args=(doc_id, "FirmatarioA", document_content_main, priv_key_A, "Thread-1")
        )
        thread2 = threading.Thread(
            target=concurrent_insert_signature,
            args=(doc_id, "FirmatarioB", document_content_main, priv_key_B, "Thread-2")
        )

        # Avvio dei thread
        thread1.start()
        thread2.start()

        # Attesa della fine dei thread
        thread1.join()
        thread2.join()

        print("\nInserimenti concorrenti completati.")
        check_for_forks(main_conn, doc_id)

    except (Exception, psycopg2.Error) as error:
        print(f"Errore nello script principale: {error}")
    finally:
        if main_conn:
            main_conn.close()