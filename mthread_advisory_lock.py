import hashlib
import psycopg2
from uuid import uuid4
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


def generate_keys_for_simulation():
    """
    Genera una coppia di chiavi RSA (privata e pubblica) a 2048 bit per la simulazione.

    Returns:
        tuple: Una tupla contenente:
               - pem_private (bytes): La chiave privata in formato PEM.
               - pem_public (bytes | None): La chiave pubblica in formato PEM, o None se non generata.
                                           In questa versione, la chiave pubblica non è usata e si restituisce None.
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048)
    pem_private = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption())
    return pem_private, None


def sign_data_for_simulation(private_key_pem: bytes, data_to_sign: bytes) -> str:
    """
    Firma i dati forniti utilizzando una chiave privata RSA PEM.

    Args:
        private_key_pem (bytes): La chiave privata in formato PEM.
        data_to_sign (bytes): I dati da firmare.

    Returns:
        str: La firma esadecimale dei dati.
    """
    private_key = serialization.load_pem_private_key(
        private_key_pem, password=None)
    signature_bytes = private_key.sign(
        data_to_sign,
        padding.PKCS1v15(),
        hashes.SHA256())
    return signature_bytes.hex()


def get_document_hash(document_content: str) -> str:
    """
    Calcola l'hash SHA256 del contenuto di un documento.

    Args:
        document_content (str): Il contenuto del documento.

    Returns:
        str: L'hash SHA256 esadecimale del contenuto.
    """
    return hashlib.sha256(document_content.encode()).hexdigest()


def generate_advisory_lock_key(document_id_str: str) -> int:
    """
    Genera una chiave bigint (intero a 64 bit) per l'advisory lock di PostgreSQL
    a partire dall'ID del documento.
    Utilizza i primi 15 caratteri esadecimali dell'hash SHA256 del document_id
    per creare un intero. Questo assicura una chiave univoca e deterministica
    per un dato document_id, adatta per `pg_advisory_xact_lock(bigint)`.

    Args:
        document_id_str (str): L'ID del documento (stringa UUID).

    Returns:
        int: Una chiave intera a 64 bit per l'advisory lock.
    """
    hasher = hashlib.sha256(document_id_str.encode('utf-8'))
    # 15 caratteri esadecimali corrispondono a 60 bit,
    # che rientrano comodamente in un bigint (64 bit).
    return int(hasher.hexdigest()[:15], 16)


def clear_table(conn) -> None:
    """
    Rimuove tutti i record dalla tabella 'signature_chain'.

    Args:
        conn: Connessione attiva al database psycopg2.
    """
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM signature_chain;")
    conn.commit()
    print("Tabella signature_chain pulita.")


def insert_genesis_block(conn, document_id_param: str, signer_name: str, doc_hash: str, signature_param: str) -> int:
    """
    Inserisce il blocco genesi (il primo blocco) per una nuova catena di firme.

    Args:
        conn: Connessione attiva al database psycopg2.
        document_id_param (str): L'ID del documento.
        signer_name (str): Il nome del firmatario del blocco genesi.
        doc_hash (str): L'hash del documento originale.
        signature_param (str): La firma del blocco genesi (basata solo sul doc_hash).

    Returns:
        int: L'ID del blocco genesi inserito.
    """
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
    print(
        f"Blocco Genesi inserito per doc {document_id_param} da {signer_name}, ID: {block_id}, Signature: {signature_param[:10]}...")
    return block_id


def concurrent_insert_signature(
        document_id_param: str,
        signer_name: str,
        document_content: str,
        private_key_pem: bytes,
        thread_name: str) -> None:
    """
    Simula l'inserimento concorrente di una firma nella catena, utilizzando
    un advisory lock transazionale di PostgreSQL (`pg_advisory_xact_lock`)
    per serializzare le operazioni critiche.
    Questa funzione è progettata per essere eseguita in un thread separato.

    Args:
        document_id_param (str): L'ID del documento a cui aggiungere la firma.
        signer_name (str): Il nome del firmatario.
        document_content (str): Il contenuto del documento (usato per l'hash).
        private_key_pem (bytes): La chiave privata PEM del firmatario.
        thread_name (str): Un nome identificativo per il thread (per il logging).
    """
    conn_thread = None
    advisory_lock_key = generate_advisory_lock_key(document_id_param)

    try:
        conn_thread = psycopg2.connect(
            dbname=db_name, user=db_user, password=db_password, host=db_host)
        # Cruciale per pg_advisory_xact_lock: il lock dura per la transazione.
        conn_thread.autocommit = False

        doc_hash = get_document_hash(document_content)

        with conn_thread.cursor() as cur:  # Un unico cursore per la transazione
            # Acquisire l'Advisory Lock transazionale
            print(
                f"[{thread_name}] Tentativo di acquisire advisory lock {advisory_lock_key} per {signer_name} su doc {document_id_param}")
            cur.execute("SELECT pg_advisory_xact_lock(%s);",
                        (advisory_lock_key,))
            print(
                f"[{thread_name}] Acquisito advisory lock {advisory_lock_key} per {signer_name}")

            # --- INIZIO SEZIONE CRITICA (protetta dall'advisory lock) ---
            # 1. Leggi l'ultimo prev_hash
            cur.execute(
                "SELECT signature FROM signature_chain WHERE document_id = %s ORDER BY id DESC LIMIT 1",
                (document_id_param,)
            )
            result = cur.fetchone()
            prev_hash = result[0] if result else None
            print(
                f"[{thread_name}] Letto prev_hash: {prev_hash[:10] if prev_hash else 'NULL'} per {signer_name}")

            # 2. Simula elaborazione / ritardo di rete
            time.sleep(random.uniform(0.1, 0.3))

            # 3. Crea la firma
            data_to_sign = (prev_hash or '').encode() + doc_hash.encode()
            current_signature = sign_data_for_simulation(
                private_key_pem, data_to_sign)

            # 4. Inserisci il nuovo blocco
            cur.execute(
                """
                INSERT INTO signature_chain (document_id, signer, document_hash, prev_hash, signature)
                VALUES (%s, %s, %s, %s, %s) RETURNING id;
                """,
                (document_id_param, signer_name,
                 doc_hash, prev_hash, current_signature)
            )
            block_id = cur.fetchone()[0]
            # --- FINE SEZIONE CRITICA ---

            # Commit della transazione, rilascia automaticamente pg_advisory_xact_lock
            conn_thread.commit()
            print(
                f"[{thread_name}] {signer_name} ha inserito il blocco ID: {block_id}. Commit e rilascio lock {advisory_lock_key}.")

    except (Exception, psycopg2.Error) as error:
        print(f"[{thread_name}] Errore per {signer_name}: {error}")
        if conn_thread:
            # Rollback della transazione, rilascia automaticamente pg_advisory_xact_lock
            conn_thread.rollback()
            print(
                f"[{thread_name}] Rollback e rilascio lock {advisory_lock_key} a causa di errore.")
    finally:
        if conn_thread:
            conn_thread.close()


def check_for_forks(conn, document_id_param: str) -> None:
    """
    Controlla la presenza di biforcazioni (forks) nella catena di firme
    per un dato document_id. Una biforcazione si verifica se più blocchi
    hanno lo stesso prev_hash. Stampa anche lo stato finale della catena.

    Args:
        conn: Connessione attiva al database psycopg2.
        document_id_param (str): L'ID del documento da controllare.
    """
    print(
        f"\n--- Controllo Biforcazioni per Documento ID: {document_id_param} ---")
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
            print("Nessuna biforcazione rilevata. La catena è sequenziale.")

        cursor.execute(
            "SELECT id, signer, prev_hash, signature FROM signature_chain WHERE document_id = %s ORDER BY id", (document_id_param,))
        print("\nStato finale della catena:")
        for row in cursor.fetchall():
            print(
                f"  ID: {row[0]}, Firmatario: {row[1]}, PrevHash: {row[2][:10] if row[2] else 'NULL'}, Signature: {row[3][:10]}...")


if __name__ == "__main__":
    main_conn = None
    try:
        main_conn = psycopg2.connect(
            dbname=db_name, user=db_user, password=db_password, host=db_host)
        clear_table(main_conn)

        doc_id_test = str(uuid4())
        document_content_main = "Contenuto del documento per test di concorrenza con advisory lock."
        doc_hash_main = get_document_hash(document_content_main)

        priv_key_gen, _ = generate_keys_for_simulation()
        genesis_signature = sign_data_for_simulation(
            priv_key_gen, doc_hash_main.encode())
        insert_genesis_block(
            main_conn, doc_id_test, "FirmatarioGenesi", doc_hash_main, genesis_signature)

        print("\nAvvio inserimenti concorrenti con Advisory Locks...")

        priv_key_A, _ = generate_keys_for_simulation()
        priv_key_B, _ = generate_keys_for_simulation()

        thread1 = threading.Thread(
            target=concurrent_insert_signature,
            args=(doc_id_test, "FirmatarioA",
                  document_content_main, priv_key_A, "Thread-1")
        )
        thread2 = threading.Thread(
            target=concurrent_insert_signature,
            args=(doc_id_test, "FirmatarioB",
                  document_content_main, priv_key_B, "Thread-2")
        )

        thread1.start()
        thread2.start()

        thread1.join()
        thread2.join()

        print("\nInserimenti concorrenti completati.")
        check_for_forks(main_conn, doc_id_test)

    except (Exception, psycopg2.Error) as error:
        print(f"Errore nello script principale: {error}")
    finally:
        if main_conn:
            main_conn.close()
