import hashlib
import psycopg2
from uuid import uuid4
from datetime import datetime
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.exceptions import InvalidSignature
import os


class Colors:
    """
    Contiene codici di escape ANSI per colorare l'output della console.
    """
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


# Emojis (opzionali, potrebbero non essere visualizzati correttamente su
# tutti i terminali)
EMOJI_SUCCESS = "✅"
EMOJI_FAIL = "❌"
EMOJI_WARN = "⚠️"
EMOJI_INFO = "ℹ️"
EMOJI_DB = "💾"
EMOJI_CHAIN = "🔗"
EMOJI_KEY = "🔑"
EMOJI_BLOCK = "🧱"
EMOJI_TAMPER = "🔨"


def generate_keys():
    """
    Genera una coppia di chiavi RSA (privata e pubblica) a 2048 bit.

    Returns:
        tuple: Una tupla contenente la chiave privata PEM e la chiave pubblica PEM.
               (pem_private, pem_public)
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048)

    pem_private = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    )

    pem_public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    return pem_private, pem_public


def hash_document(doc_bytes: bytes) -> str:
    """
    Calcola l'hash SHA256 di un documento.

    Args:
        doc_bytes (bytes): Il contenuto del documento come bytes.

    Returns:
        str: La rappresentazione esadecimale dell'hash SHA256.
    """
    return hashlib.sha256(doc_bytes).hexdigest()


def sign_data(data: bytes, private_key_pem: bytes) -> str:
    """
    Firma i dati forniti utilizzando una chiave privata RSA.

    Args:
        data (bytes): I dati da firmare.
        private_key_pem (bytes): La chiave privata in formato PEM.

    Returns:
        str: La firma digitale come stringa esadecimale.
    """
    private_key = serialization.load_pem_private_key(
        private_key_pem, password=None)

    signature = private_key.sign(
        data,
        padding.PKCS1v15(),
        hashes.SHA256()
    )

    return signature.hex()


def verify_signature(data: bytes, signature_hex: str,
                     public_key_pem: bytes) -> bool:
    """
    Verifica una firma digitale utilizzando una chiave pubblica RSA.

    Args:
        data (bytes): I dati originali che sono stati firmati.
        signature_hex (str): La firma digitale come stringa esadecimale.
        public_key_pem (bytes): La chiave pubblica in formato PEM.

    Returns:
        bool: True se la firma è valida, False altrimenti.
    """
    public_key = serialization.load_pem_public_key(public_key_pem)

    try:
        signature_bytes = bytes.fromhex(signature_hex)
        public_key.verify(
            signature_bytes,
            data,
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        return True
    except InvalidSignature:
        return False
    except Exception as e:
        print(
            f"{Colors.FAIL}{EMOJI_FAIL} Errore durante la verifica della firma: {e}{Colors.ENDC}")
        return False


def insert_signature_chain(document: bytes, signer: str, conn, private_key_pem: bytes, is_first_call: bool,
                           original_doc_content: str):
    """
    Crea un nuovo blocco nella catena di firme e lo inserisce nel database.

    Il blocco contiene l'hash del documento, l'hash del blocco precedente
    (se esiste) e una firma di questi due elementi.

    Args:
        document (bytes): Il contenuto del documento da firmare (per calcolare l'hash).
        signer (str): Il nome del firmatario.
        conn: La connessione al database psycopg2.
        private_key_pem (bytes): La chiave privata del firmatario in formato PEM.
        is_first_call (bool): True se è la prima firma inserita in questa sessione,
                              per stampare un'intestazione generale.
        original_doc_content (str): Il contenuto originale del documento come stringa,
                                    per la stampa.
    """
    if is_first_call:
        print(
            f"\n{
                Colors.HEADER}{EMOJI_CHAIN}==== Sequenza Firme Inserite nella Catena ===={
                Colors.ENDC}")
        print(
            f"{Colors.OKCYAN}Documento Originale: \"{original_doc_content}\"{Colors.ENDC}")
        print(
            f"{
                Colors.OKCYAN}Hash Documento Originale: {
                hash_document(document)}{
                Colors.ENDC}")
        print(Colors.OKCYAN + "-" * 70 + Colors.ENDC)

    document_hash = hash_document(document)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT signature FROM signature_chain ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    prev_hash = row[0] if row else None

    chain_input = (prev_hash or '').encode() + document_hash.encode()
    signature = sign_data(chain_input, private_key_pem)

    document_id = str(uuid4())

    cursor.execute("""
        INSERT INTO signature_chain (document_id, signer, document_hash, prev_hash, signature)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """, (document_id, signer, document_hash, prev_hash, signature))

    inserted_id = cursor.fetchone()[0]
    conn.commit()

    print(f"{Colors.OKGREEN}{EMOJI_BLOCK} ID Blocco: {inserted_id}{Colors.ENDC}")
    print(f"  {Colors.OKBLUE}Firmatario: {signer}{Colors.ENDC}")
    print(
        f"  {
            Colors.OKBLUE}Hash Documento Firmato: {document_hash}{
            Colors.ENDC}")
    print(
        f"  {
            Colors.OKBLUE}Hash Catena Precedente: {
            prev_hash if prev_hash else 'N/A (Blocco Genesi)'}{
                Colors.ENDC}")
    print(
        f"  {Colors.OKBLUE}Hash Catena Corrente (Firma del Blocco): {signature[:64]}...{Colors.ENDC}")
    print(Colors.OKCYAN + "-" * 70 + Colors.ENDC)


def verify_chain(conn, firmatari_data: dict, user_context: str = ""):
    """
    Verifica l'integrità dell'intera catena di firme memorizzata nel database.

    Controlla che ogni blocco sia correttamente collegato al precedente e che
    la firma di ogni blocco sia valida rispetto ai dati firmati e alla chiave
    pubblica del firmatario.

    Args:
        conn: La connessione al database psycopg2.
        firmatari_data (dict): Un dizionario che mappa i nomi dei firmatari
                               alle loro chiavi pubbliche PEM.
        user_context (str, optional): Una stringa per descrivere il contesto
                                      della verifica (es. nome utente).
                                      Defaults to "".

    Returns:
        bool: True se l'intera catena è valida, False altrimenti.
    """
    print(
        f"\n{
            Colors.HEADER}{EMOJI_CHAIN}==== Verifica Integrità Catena Firme (Contesto: {user_context}) ===={
            Colors.ENDC}")

    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, signer, document_hash, prev_hash, signature FROM signature_chain ORDER BY id ASC")
    records = cursor.fetchall()

    if not records:
        print(
            f"{
                Colors.WARNING}{EMOJI_INFO} Nessuna firma trovata nella catena per la verifica.{
                Colors.ENDC}")
        return True

    is_chain_valid = True
    last_block_signature = None

    for i, row_data in enumerate(records):
        record_id, signer_name, doc_hash_stored, prev_hash_stored, current_signature_stored = row_data

        print(
            f"\n{
                Colors.OKCYAN}Verifica Blocco ID: {record_id} (Firmatario: {signer_name}){
                Colors.ENDC}")

        if i == 0:
            if prev_hash_stored is not None:
                print(
                    f"  {
                        Colors.FAIL}{EMOJI_FAIL} ERRORE: Il blocco genesi (ID: {record_id}) dovrebbe avere prev_hash NULL, invece è '{prev_hash_stored}'.{
                        Colors.ENDC}")
                is_chain_valid = False
        else:
            if prev_hash_stored != last_block_signature:
                print(
                    f"  {
                        Colors.FAIL}{EMOJI_FAIL} ERRORE: prev_hash del blocco {record_id} ('{prev_hash_stored}') non corrisponde alla signature del blocco precedente ('{
                        last_block_signature[
                            :10]}...').{
                        Colors.ENDC}")
                is_chain_valid = False
            else:
                print(
                    f"  {
                        Colors.OKGREEN}{EMOJI_SUCCESS} OK: prev_hash ('{
                        prev_hash_stored[
                            :10]}...') corrisponde alla signature del blocco precedente.{
                        Colors.ENDC}")

        public_key_pem = firmatari_data.get(signer_name)

        if not public_key_pem:
            print(
                f"  {
                    Colors.FAIL}{EMOJI_FAIL} ERRORE: Chiave pubblica {EMOJI_KEY} non trovata per il firmatario '{signer_name}'. Impossibile verificare la firma del blocco {record_id}.{
                    Colors.ENDC}")
            is_chain_valid = False
            last_block_signature = current_signature_stored
            continue

        chain_input_to_verify = (
            prev_hash_stored or '').encode() + doc_hash_stored.encode()

        if verify_signature(chain_input_to_verify,
                            current_signature_stored, public_key_pem):
            print(
                f"  {
                    Colors.OKGREEN}{EMOJI_SUCCESS} OK: La firma del blocco {record_id} è valida.{
                    Colors.ENDC}")
        else:
            print(
                f"  {
                    Colors.FAIL}{EMOJI_FAIL} ERRORE: La firma del blocco {record_id} NON è valida (possibile manomissione di document_hash o prev_hash).{
                    Colors.ENDC}")
            is_chain_valid = False

        last_block_signature = current_signature_stored

    cursor.close()
    print(Colors.HEADER + "-" * 70 + Colors.ENDC)

    if is_chain_valid:
        print(f"{Colors.OKGREEN}{EMOJI_SUCCESS} RISULTATO VERIFICA ({user_context}): L'intera catena di firme è VALIDA.{Colors.ENDC}")
    else:
        print(f"{Colors.FAIL}{EMOJI_FAIL} RISULTATO VERIFICA ({user_context}): L'intera catena di firme NON È VALIDA. Controllare gli errori sopra.{Colors.ENDC}")

    print(Colors.HEADER + "-" * 70 + Colors.ENDC)

    return is_chain_valid


def clear_signature_table(db_name_param, super_user_param,
                          super_password_param, db_host_param):
    """
    Pulisce la tabella 'signature_chain' nel database.
    Questa funzione richiede privilegi di superutente per eseguire DELETE.

    Args:
        db_name_param (str): Nome del database.
        super_user_param (str): Nome utente del superutente del database.
        super_password_param (str): Password del superutente del database.
        db_host_param (str): Host del database.
    """
    conn_super_clear = None

    try:
        print(
            f"\n{
                Colors.WARNING}{EMOJI_DB} Tentativo di pulire la tabella signature_chain come utente '{super_user_param}'...{
                Colors.ENDC}")
        conn_super_clear = psycopg2.connect(
            dbname=db_name_param,
            user=super_user_param,
            password=super_password_param,
            host=db_host_param)
        with conn_super_clear.cursor() as cursor:
            cursor.execute("DELETE FROM signature_chain;")
        conn_super_clear.commit()
        print(
            f"{
                Colors.OKGREEN}{EMOJI_SUCCESS} Tabella signature_chain pulita con successo.{
                Colors.ENDC}")
    except (Exception, psycopg2.Error) as error:
        print(f"{Colors.FAIL}{EMOJI_FAIL} ERRORE durante la pulizia della tabella come '{super_user_param}': {error}{Colors.ENDC}")
        if conn_super_clear:
            conn_super_clear.rollback()
    finally:
        if conn_super_clear:
            conn_super_clear.close()


if __name__ == "__main__":
    # Variabili di connessione al DB, configurabili tramite ENV o con valori
    # di default
    app_db_user = os.environ.get("APP_DB_USER", "app_user")
    app_db_password = os.environ.get("APP_DB_PASSWORD", "app_password")
    super_db_user = os.environ.get("SUPER_DB_USER", "postgres")
    super_db_password = os.environ.get("SUPER_DB_PASSWORD", "postgres")
    db_name = os.environ.get("DB_NAME", "signature_demo")
    db_host = os.environ.get("DB_HOST", "localhost")

    doc_content = "Contenuto documento firmato da più persone"
    doc_bytes = doc_content.encode("utf-8")

    firmatari_list = []
    nomi_firmatari = ["Antonio", "Marianna", "Claudio"]

    for nome in nomi_firmatari:
        priv_key, pub_key = generate_keys()
        firmatari_list.append({"nome": nome, "priv": priv_key, "pub": pub_key})

    firmatari_pub_keys = {f["nome"]: f["pub"] for f in firmatari_list}

    clear_signature_table(db_name, super_db_user, super_db_password, db_host)

    print(
        f"\n{
            Colors.BOLD}{
            Colors.HEADER}===== SCENARIO 1: Utente Applicativo ({app_db_user}) ====={
                Colors.ENDC}")

    conn_app = None

    try:
        print(
            f"{EMOJI_DB} Tentativo di connessione al database '{db_name}' come utente '{
                Colors.OKBLUE}{app_db_user}{
                Colors.ENDC}'...")

        conn_app = psycopg2.connect(
            dbname=db_name,
            user=app_db_user,
            password=app_db_password,
            host=db_host)

        print(
            f"{Colors.OKGREEN}{EMOJI_SUCCESS} Connessione come {app_db_user} riuscita.{Colors.ENDC}")

        for i, firmatario_info in enumerate(firmatari_list):
            insert_signature_chain(
                doc_bytes,
                firmatario_info["nome"],
                conn_app,
                firmatario_info["priv"],
                i == 0,
                doc_content)

        verify_chain(
            conn_app,
            firmatari_pub_keys,
            f"{app_db_user} - Post Inserimento")

        print(
            f"\n{
                Colors.WARNING}{EMOJI_TAMPER}---- 1.2 Tentativo di Manomissione UPDATE (come {app_db_user}) ----{
                Colors.ENDC}")

        if len(firmatari_list) > 1:
            target_signer_app = firmatari_list[1]["nome"]
            tampered_block_id_app = None
            with conn_app.cursor() as cursor_select_app:
                cursor_select_app.execute(
                    "SELECT id FROM signature_chain WHERE signer = %s ORDER BY id ASC LIMIT 1",
                    (target_signer_app,
                     ))
                tampered_block_data_app = cursor_select_app.fetchone()

            if tampered_block_data_app:
                tampered_block_id_app = tampered_block_data_app[0]
                new_fake_hash_app = "hash_manomesso_da_app_user"
                print(f"{EMOJI_INFO} Tentativo di UPDATE del document_hash del blocco ID: {tampered_block_id_app} (Firmatario: {target_signer_app}) come '{app_db_user}'.")
                try:
                    with conn_app.cursor() as cursor_update_app:
                        cursor_update_app.execute(
                            "UPDATE signature_chain SET document_hash = %s WHERE id = %s",
                            (new_fake_hash_app,
                             tampered_block_id_app))
                    conn_app.commit()
                    print(
                        f"{Colors.FAIL}{EMOJI_FAIL} ERRORE INASPETTATO: L'UPDATE come {app_db_user} è riuscito. Controllare i permessi RLS/GRANT.{Colors.ENDC}")
                except psycopg2.Error as db_error:
                    print(
                        f"{
                            Colors.OKGREEN}{EMOJI_SUCCESS} SUCCESSO: Tentativo di UPDATE BLOCCATO dal DB per '{app_db_user}' come previsto!{
                            Colors.ENDC}")
                    print(
                        f"  {
                            Colors.OKCYAN}Errore DB (SQLSTATE {
                            db_error.pgcode}): {
                            db_error.pgerror.strip()}{
                            Colors.ENDC}")
                    conn_app.rollback()
            else:
                print(
                    f"{
                        Colors.WARNING}{EMOJI_WARN} Blocco da manomettere (firmatario: {target_signer_app}) non trovato.{
                        Colors.ENDC}")
        else:
            print(
                f"{
                    Colors.WARNING}{EMOJI_WARN} Non ci sono abbastanza firmatari per testare la manomissione.{
                    Colors.ENDC}")

        verify_chain(
            conn_app,
            firmatari_pub_keys,
            f"{app_db_user} - Post Tentativo UPDATE Bloccato")

    except psycopg2.OperationalError as e:
        print(
            f"{Colors.FAIL}{EMOJI_FAIL} Errore di connessione ({app_db_user}): {e}{Colors.ENDC}")
        print(f"{Colors.WARNING}Verifica che il DB '{db_name}' esista, PostgreSQL sia in esecuzione, e l'utente '{app_db_user}' sia configurato.{Colors.ENDC}")
    except (Exception, psycopg2.Error) as error:
        print(
            f"{
                Colors.FAIL}{EMOJI_FAIL} Errore imprevisto nello scenario {app_db_user}: {error}{
                Colors.ENDC}")
        if conn_app:
            conn_app.rollback()
    finally:
        if conn_app:
            conn_app.close()
            print(f"\n{EMOJI_DB} Connessione '{app_db_user}' chiusa.")

    print(
        f"\n{
            Colors.BOLD}{
            Colors.HEADER}===== SCENARIO 2: Utente Privilegiato ({super_db_user}) ====={
                Colors.ENDC}")

    conn_super_scenario = None

    try:
        clear_signature_table(
            db_name,
            super_db_user,
            super_db_password,
            db_host)

        print(
            f"{EMOJI_DB} Tentativo di connessione al database '{db_name}' come utente '{
                Colors.WARNING}{super_db_user}{
                Colors.ENDC}'...")
        conn_super_scenario = psycopg2.connect(
            dbname=db_name,
            user=super_db_user,
            password=super_db_password,
            host=db_host)
        print(
            f"{
                Colors.OKGREEN}{EMOJI_SUCCESS} Connessione come '{super_db_user}' riuscita.{
                Colors.ENDC}")

        for i, firmatario_info in enumerate(firmatari_list):
            insert_signature_chain(
                doc_bytes,
                firmatario_info["nome"],
                conn_super_scenario,
                firmatario_info["priv"],
                i == 0,
                doc_content)

        verify_chain(
            conn_super_scenario,
            firmatari_pub_keys,
            f"{super_db_user} - Post Inserimento")

        print(
            f"\n{
                Colors.WARNING}{EMOJI_TAMPER}---- 2.2 Manomissione UPDATE (come {super_db_user}) ----{
                Colors.ENDC}")

        if len(firmatari_list) > 1:
            target_signer_super = firmatari_list[1]["nome"]
            tampered_block_id_super = None
            with conn_super_scenario.cursor() as cursor_select_super:
                cursor_select_super.execute(
                    "SELECT id FROM signature_chain WHERE signer = %s ORDER BY id ASC LIMIT 1",
                    (target_signer_super,
                     ))
                tampered_block_data_super = cursor_select_super.fetchone()

            if tampered_block_data_super:
                tampered_block_id_super = tampered_block_data_super[0]
                new_fake_hash_super = "hash_manomesso_da_superuser_abcdef12345"
                print(f"{EMOJI_INFO} Esecuzione UPDATE del document_hash del blocco ID: {tampered_block_id_super} (Firmatario: {target_signer_super}) come '{super_db_user}'.")
                try:
                    with conn_super_scenario.cursor() as cursor_update_super:
                        cursor_update_super.execute(
                            "UPDATE signature_chain SET document_hash = %s WHERE id = %s",
                            (new_fake_hash_super,
                             tampered_block_id_super))
                    conn_super_scenario.commit()
                    print(
                        f"{
                            Colors.OKGREEN}{EMOJI_SUCCESS} Manomissione UPDATE (come {super_db_user}) effettuata con successo a livello DB.{
                            Colors.ENDC}")
                except psycopg2.Error as db_error:
                    print(
                        f"{
                            Colors.FAIL}{EMOJI_FAIL} ERRORE INASPETTATO: L'UPDATE come '{super_db_user}' è fallito: {db_error}{
                            Colors.ENDC}")
                    conn_super_scenario.rollback()
            else:
                print(
                    f"{
                        Colors.WARNING}{EMOJI_WARN} Blocco da manomettere (firmatario: {target_signer_super}) non trovato.{
                        Colors.ENDC}")
        else:
            print(
                f"{
                    Colors.WARNING}{EMOJI_WARN} Non ci sono abbastanza firmatari per testare la manomissione.{
                    Colors.ENDC}")

        verify_chain(conn_super_scenario, firmatari_pub_keys,
                     f"{super_db_user} - Post Manomissione DB")

    except psycopg2.OperationalError as e:
        print(
            f"{Colors.FAIL}{EMOJI_FAIL} Errore di connessione ({super_db_user}): {e}{Colors.ENDC}")
    except (Exception, psycopg2.Error) as error:
        print(
            f"{
                Colors.FAIL}{EMOJI_FAIL} Errore imprevisto nello scenario {super_db_user}: {error}{
                Colors.ENDC}")
        if conn_super_scenario:
            conn_super_scenario.rollback()
    finally:
        if conn_super_scenario:
            conn_super_scenario.close()
            print(f"\n{EMOJI_DB} Connessione '{super_db_user}' chiusa.")

    print(
        f"\n{
            Colors.BOLD}{
            Colors.OKGREEN}Fine della dimostrazione.{
                Colors.ENDC}")
