import os
import json
import csv
import logging
import tempfile
import gc  # Ajout de gc pour le garbage collection
from typing import Tuple, List, Dict, Any, Optional, Generator
from google.cloud import storage
from flask import current_app

logger = logging.getLogger(__name__)

def get_csv_path(filename: str) -> str:
    """Get CSV file path from GCS or local storage"""
    if os.getenv('GOOGLE_CLOUD_PROJECT'):
        try:
            storage_client = storage.Client()
            bucket_name = current_app.config.get('DATA_BUCKET', os.environ.get('DATA_BUCKET', 'tilto-data'))
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(f'csv/{filename}')
            _, temp_path = tempfile.mkstemp(suffix='.csv')
            blob.download_to_filename(temp_path)
            logger.info(f"Downloaded CSV from GCS: {filename}")
            return temp_path
        except Exception as e:
            logger.error(f"Error downloading CSV from GCS: {str(e)}")
            raise
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, 'data/csv', filename)

def clean_quotes(text: Optional[str]) -> Optional[str]:
    """Clean quotes from text values"""
    if text:
        return text.strip('"""').strip('"')
    return text

def parse_bool(value: str) -> bool:
    """Convert string to boolean"""
    return str(value).upper() in ('TRUE', '1', 'YES')

def safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    """Safely convert value to integer"""
    try:
        return int(float(value)) if value else default
    except (ValueError, TypeError):
        return default

def safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    """Safely convert value to float"""
    try:
        return float(value) if value else default
    except (ValueError, TypeError):
        return default

def load_csv_file(filename: str, processor_func) -> Any:
    """Generic function to load CSV file and process it line by line to save memory"""
    csv_path = None
    reader = None
    try:
        csv_path = get_csv_path(filename)
        logger.info(f"Reading: {csv_path}")
        with open(csv_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file, delimiter=',', quotechar='"')
            result = processor_func(reader)
        logger.info(f"Successfully loaded {filename}")
        return result
    except Exception as e:
        logger.error(f"Error loading {filename}: {str(e)}", exc_info=True)
        raise
    finally:
        if reader is not None:
            del reader
        if os.getenv('GOOGLE_CLOUD_PROJECT') and csv_path:
            try:
                os.remove(csv_path)
            except Exception as e:
                logger.warning(f"Could not remove temporary file {csv_path}: {e}")

def load_quiz_catalog() -> List[Dict[str, Any]]:
    def process_quiz(reader: Generator):
        result = []
        for row in reader:
            result.append({
                "quiz_id": row['quiz_id'],
                "quiz_type": row['quiz_type'],
                "description": row['description'],
                "short_description": row['short_description'],
                "image_url": row['image_url'],
                "quiz_category": row['quiz_category'],
                "questions_count": safe_int(row['questions_count'], 0),
                "is_active": parse_bool(row.get('is_active', 'TRUE'))
            })
        return result
    return load_csv_file('quiz_catalog.csv', process_quiz)

def load_product_catalog() -> List[Dict[str, Any]]:
    def process_products(reader: Generator):
        products = []
        for row in reader:
            currency = (row.get('currency') or 'eur').lower()
            products.append({
                "product_id": row['product_id'],
                "product_name": row['product_name'],
                "product_type": row['product_type'],
                "description": row.get('description', ''),
                "short_description": row.get('short_description', ''),
                "image_url": row.get('image_url'),
                "product_category": row.get('product_category', ''),
                "base_price": safe_int(row.get('base_price', 0)),
                "vat_price": safe_int(row.get('vat_price', 0)),
                "unit_amount": safe_int(row.get('unit_amount', 0)),
                "vat_rate": safe_float(row.get('vat_rate', 20.00)),
                "currency": currency,
                "country_code": row.get('country_code', 'FR'),
                "emoji": row.get('emoji'),
                "subtitle": row.get('subtitle'),
                "is_featured": parse_bool(row.get('is_featured', 'FALSE')),
                "button_text": row.get('button_text'),
                "is_active": parse_bool(row.get('is_active', 'TRUE'))
            })
        return products
    return load_csv_file('product_catalog.csv', process_products)

def load_product_features() -> List[Dict[str, Any]]:
    def process_features(reader: Generator):
        features = []
        for row in reader:
            features.append({
                "product_id": row['product_id'],
                "feature_order": safe_int(row['feature_order']),
                "feature_icon": row['feature_icon'],
                "feature_text": row['feature_text'],
                "is_active": parse_bool(row.get('is_active', 'TRUE'))
            })
        return features
    return load_csv_file('product_features.csv', process_features)

def load_product_catalog_items() -> List[Dict[str, Any]]:
    def process_items(reader: Generator):
        items = []
        for row in reader:
            items.append({
                "item_id": row['item_id'],
                "item_name": row['item_name'],
                "item_type": row['item_type'],
                "description": row['description'],
                "image_url": row.get('image_url'),
                "item_category": row['item_category'],
                "base_price": safe_int(row['base_price']),
                "vat_price": safe_int(row['vat_price']),
                "unit_amount": safe_int(row['unit_amount']),
                "vat_rate": safe_float(row['vat_rate']),
                "currency": (row.get('currency') or 'eur').lower(),
                "is_active": parse_bool(row.get('is_active', 'TRUE')),
                "country_code": row['country_code']
            })
        return items
    return load_csv_file('product_catalog_items.csv', process_items)

def load_product_items() -> List[Dict[str, Any]]:
    def process_relations(reader: Generator):
        relations = []
        for row in reader:
            relations.append({
                "product_id": row['product_id'],
                "item_id": row['item_id'],
                "country_code": row['country_code'],
                "is_active": parse_bool(row.get('is_active', 'TRUE')),
                "quantity": safe_int(row['quantity'], 1)
            })
        return relations
    return load_csv_file('product_items.csv', process_relations)

def load_item_quiz() -> List[Dict[str, Any]]:
    def process_item_quiz(reader: Generator):
        relations = []
        for row in reader:
            relations.append({
                "item_id": row['item_id'],
                "quiz_id": row['quiz_id'],
                "is_active": parse_bool(row.get('is_active', 'TRUE'))
            })
        return relations
    return load_csv_file('item_quiz.csv', process_item_quiz)

def load_quiz_questions() -> List[Dict[str, Any]]:
    def process_quiz_questions(reader: Generator):
        quiz_questions = []
        for row in reader:
            quiz_questions.append({
                "quiz_id": row['quiz_id'],
                "question_id": safe_int(row['question_id']),
                "question_ranking": safe_int(row['question_ranking']),
                "is_active": True
            })
        return quiz_questions
    return load_csv_file('quiz_questions.csv', process_quiz_questions)

def load_questions() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    def process_questions(reader: Generator):
        questions: Dict[int, Dict[str, Any]] = {}
        choices: List[Dict[str, Any]] = []
        for row in reader:
            qid = safe_int(row['question_id'])
            if qid not in questions:
                cond = row.get('condition_value')
                if cond:
                    try:
                        cond = json.loads(cond) if isinstance(cond, str) else cond
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in condition_value for question {qid}")
                        cond = None
                questions[qid] = {
                    "question_id": qid,
                    "question_type": row['question_type'],
                    "min_choices": safe_int(row.get('min_choices')),
                    "max_choices": safe_int(row.get('max_choices')),
                    "parent_question_id": safe_int(row.get('parent_question_id')),
                    "condition_value": cond,
                    "is_conditional": parse_bool(row.get('is_conditional', 'FALSE')),
                    "question": clean_quotes(row['question_text']),
                    "question_category": row['question_category'],
                    "question_description": clean_quotes(row.get('question_description')),
                    "hint": clean_quotes(row.get('hint')),
                    "media_type": row.get('media_type'),
                    "media_url": row.get('media_url'),
                    "country_code": row['country_code'],
                    "is_active": parse_bool(row.get('is_active', 'TRUE'))
                }
            choice_val = safe_int(row.get('choice_value'))
            if choice_val is not None:
                choices.append({
                    "question_id": qid,
                    "next_question_id": safe_int(row.get('next_question_id')),
                    "choice_value": choice_val,
                    "choice_text": clean_quotes(row['choice_text']),
                    "choice_description": clean_quotes(row.get('choice_description')),
                    "additional_info": clean_quotes(row.get('additional_info')),
                    "country_code": row['country_code'],
                    "choice_media_url": row.get('choice_media_url'),
                    "choice_media_type": row.get('choice_media_type'),
                    "max_character_input": safe_int(row.get('max_character_input')),
                    "is_active": parse_bool(row.get('is_active', 'TRUE'))
                })
        return list(questions.values()), choices
    return load_csv_file('questions_catalog.csv', process_questions)

def load_quiz_result() -> List[Dict[str, Any]]:
    def process_quiz_result(reader: Generator):
        results = []
        for row in reader:
            if row['quiz_id'] and row['result_step_id']:
                results.append({
                    "quiz_id": row['quiz_id'],
                    "result_step_id": row['result_step_id'],
                    "result_step_ranking": safe_int(row['result_step_ranking']),
                    "template_html": row['template_html'],
                    "prompt_system": clean_quotes(row.get('prompt_system', '')),
                    "prompt_instruction": clean_quotes(row['prompt_instruction']),
                    "prompt_knowledge": clean_quotes(row.get('prompt_knowledge', '')),
                    "validation_criteria": clean_quotes(row.get('validation_criteria', '')),
                    "is_active": parse_bool(row['is_active'])
                })
        return results
    return load_csv_file('quiz_result.csv', process_quiz_result)

def upsert_soft_delete(
    cursor,
    table_name: str,
    primary_key: str,
    csv_data: List[Dict[str, Any]],
    insert_sql: str,
    update_sql: str,
    existing_rows_sql: str,
    get_pk=lambda row: row,
    get_pk_csv=lambda row: row[primary_key],
    get_insert_params=lambda row: tuple(row.values()),
    get_update_params=lambda row: tuple(row.values()),
    batch_size: int = 100
):
    cursor.execute(existing_rows_sql)
    existing_rows = cursor.fetchall()
    existing_ids_in_db = set(get_pk(r) for r in existing_rows)
    del existing_rows

    csv_ids = set()
    for i in range(0, len(csv_data), batch_size):
        batch = csv_data[i:i+batch_size]
        for row in batch:
            rid = get_pk_csv(row)
            csv_ids.add(rid)
            if rid in existing_ids_in_db:
                cursor.execute(update_sql, get_update_params(row))
            else:
                cursor.execute(insert_sql, get_insert_params(row))
        cursor.connection.commit()
        del batch
        gc.collect()

    to_delete = existing_ids_in_db - csv_ids
    if to_delete:
        keys = list(to_delete)
        for i in range(0, len(keys), 500):
            batch = keys[i:i+500]
            placeholders = ",".join(["%s"] * len(batch))
            sql = f"UPDATE {table_name} SET is_active = FALSE WHERE {primary_key} IN ({placeholders})"
            cursor.execute(sql, batch)
            cursor.connection.commit()
            del batch
        del keys

def update_quiz_catalog():
    logger.info("Updating quiz_catalog (soft delete)")
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        quizzes = load_quiz_catalog()
        insert_sql = '''
            INSERT INTO quiz_catalog (
                quiz_id, quiz_type, description, short_description,
                image_url, quiz_category, questions_count, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        '''
        update_sql = '''
            UPDATE quiz_catalog
            SET quiz_type=%s, description=%s, short_description=%s,
                image_url=%s, quiz_category=%s, questions_count=%s, is_active=%s
            WHERE quiz_id=%s
        '''
        existing_sql = "SELECT quiz_id FROM quiz_catalog"
        upsert_soft_delete(
            cursor, "quiz_catalog", "quiz_id", quizzes,
            insert_sql, update_sql, existing_sql,
            get_pk=lambda r: r[0],
            get_pk_csv=lambda r: r['quiz_id'],
            get_insert_params=lambda r: (
                r['quiz_id'], r['quiz_type'], r['description'],
                r['short_description'], r['image_url'], r['quiz_category'],
                r['questions_count'], r['is_active']
            ),
            get_update_params=lambda r: (
                r['quiz_type'], r['description'], r['short_description'],
                r['image_url'], r['quiz_category'], r['questions_count'],
                r['is_active'], r['quiz_id']
            )
        )
        mysql.connection.commit()
    except Exception:
        mysql.connection.rollback()
        logger.exception("Error updating quiz_catalog")
        raise
    finally:
        cursor.close()

def update_products():
    logger.info("Updating product tables (soft delete)")
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        products = load_product_catalog()
        insert_sql = '''INSERT INTO product_catalog (
            product_id, product_name, product_type, description,
            short_description, image_url, product_category,
            base_price, vat_price, unit_amount, vat_rate,
            currency, is_active, country_code, emoji, subtitle,
            is_featured, button_text
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)'''
        update_sql = '''UPDATE product_catalog
            SET product_name=%s, product_type=%s, description=%s,
                short_description=%s, image_url=%s, product_category=%s,
                base_price=%s, vat_price=%s, unit_amount=%s, vat_rate=%s,
                currency=%s, is_active=%s, country_code=%s, emoji=%s,
                subtitle=%s, is_featured=%s, button_text=%s
            WHERE product_id=%s'''
        existing_sql = "SELECT product_id FROM product_catalog"
        upsert_soft_delete(
            cursor, "product_catalog", "product_id", products,
            insert_sql, update_sql, existing_sql,
            get_pk=lambda r: r[0],
            get_pk_csv=lambda r: r['product_id'],
            get_insert_params=lambda r: (
                r['product_id'], r['product_name'], r['product_type'],
                r['description'], r['short_description'], r['image_url'],
                r['product_category'], r['base_price'], r['vat_price'],
                r['unit_amount'], r['vat_rate'], r['currency'],
                r['is_active'], r['country_code'], r.get('emoji'),
                r.get('subtitle'), r.get('is_featured', False),
                r.get('button_text')
            ),
            get_update_params=lambda r: (
                r['product_name'], r['product_type'], r['description'],
                r['short_description'], r['image_url'], r['product_category'],
                r['base_price'], r['vat_price'], r['unit_amount'],
                r['vat_rate'], r['currency'], r['is_active'],
                r['country_code'], r.get('emoji'), r.get('subtitle'),
                r.get('is_featured', False), r.get('button_text'),
                r['product_id']
            )
        )
        del products; gc.collect()

        items = load_product_catalog_items()
        insert_sql_i = '''INSERT INTO product_catalog_items (
            item_id, item_name, item_type, description,
            image_url, item_category, base_price,
            vat_price, unit_amount, vat_rate,
            currency, is_active, country_code
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)'''
        update_sql_i = '''UPDATE product_catalog_items
            SET item_name=%s, item_type=%s, description=%s,
                image_url=%s, item_category=%s, base_price=%s,
                vat_price=%s, unit_amount=%s, vat_rate=%s,
                currency=%s, is_active=%s, country_code=%s
            WHERE item_id=%s'''
        existing_sql_i = "SELECT item_id FROM product_catalog_items"
        upsert_soft_delete(
            cursor, "product_catalog_items", "item_id", items,
            insert_sql_i, update_sql_i, existing_sql_i,
            get_pk=lambda r: r[0],
            get_pk_csv=lambda r: r['item_id'],
            get_insert_params=lambda r: (
                r['item_id'], r['item_name'], r['item_type'],
                r['description'], r['image_url'], r['item_category'],
                r['base_price'], r['vat_price'], r['unit_amount'],
                r['vat_rate'], r['currency'], r['is_active'],
                r['country_code']
            ),
            get_update_params=lambda r: (
                r['item_name'], r['item_type'], r['description'],
                r['image_url'], r['item_category'], r['base_price'],
                r['vat_price'], r['unit_amount'], r['vat_rate'],
                r['currency'], r['is_active'], r['country_code'],
                r['item_id']
            )
        )
        del items; gc.collect()

        relations = load_product_items()
        insert_sql_r = '''INSERT INTO product_items (
            product_id, item_id, quantity, is_active
        ) VALUES (%s, %s, %s, %s)'''
        update_sql_r = '''UPDATE product_items
            SET quantity=%s, is_active=%s
            WHERE product_id=%s AND item_id=%s'''
        existing_sql_r = "SELECT product_id, item_id FROM product_items"
        upsert_soft_delete(
            cursor, "product_items", "(product_id,item_id)", relations,
            insert_sql_r, update_sql_r, existing_sql_r,
            get_pk=lambda r: (r[0], r[1]),
            get_pk_csv=lambda r: (r['product_id'], r['item_id']),
            get_insert_params=lambda r: (
                r['product_id'], r['item_id'], r['quantity'], r['is_active']
            ),
            get_update_params=lambda r: (
                r['quantity'], r['is_active'], r['product_id'], r['item_id']
            )
        )
        del relations; gc.collect()

        mysql.connection.commit()
    except Exception:
        mysql.connection.rollback()
        logger.exception("Error updating product tables")
        raise
    finally:
        cursor.close()

def update_product_features():
    logger.info("Updating product_features (soft delete)")
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        features = load_product_features()
        insert_sql = '''
            INSERT INTO product_features (
                product_id, feature_order, feature_icon, feature_text, is_active
            ) VALUES (%s, %s, %s, %s, %s)
        '''
        update_sql = '''
            UPDATE product_features
            SET feature_icon=%s, feature_text=%s, is_active=%s
            WHERE product_id=%s AND feature_order=%s
        '''
        existing_sql = "SELECT product_id, feature_order FROM product_features"
        upsert_soft_delete(
            cursor, "product_features", "(product_id,feature_order)", features,
            insert_sql, update_sql, existing_sql,
            get_pk=lambda r: (r[0], r[1]),
            get_pk_csv=lambda r: (r['product_id'], r['feature_order']),
            get_insert_params=lambda r: (
                r['product_id'], r['feature_order'], r['feature_icon'],
                r['feature_text'], r['is_active']
            ),
            get_update_params=lambda r: (
                r['feature_icon'], r['feature_text'], r['is_active'],
                r['product_id'], r['feature_order']
            )
        )
        mysql.connection.commit()
    except Exception:
        mysql.connection.rollback()
        logger.exception("Error updating product_features")
        raise
    finally:
        cursor.close()

def update_item_quiz():
    logger.info("Updating item_quiz (soft delete)")
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        relations = load_item_quiz()
        for r in relations:
            r.setdefault('is_active', True)
        insert_sql = '''
            INSERT INTO item_quiz (item_id, quiz_id, is_active)
            VALUES (%s, %s, %s)
        '''
        update_sql = '''
            UPDATE item_quiz
            SET is_active=%s
            WHERE item_id=%s AND quiz_id=%s
        '''
        existing_sql = "SELECT item_id, quiz_id FROM item_quiz"
        upsert_soft_delete(
            cursor, "item_quiz", "(item_id,quiz_id)", relations,
            insert_sql, update_sql, existing_sql,
            get_pk=lambda r: (r[0], r[1]),
            get_pk_csv=lambda r: (r['item_id'], r['quiz_id']),
            get_insert_params=lambda r: (r['item_id'], r['quiz_id'], r['is_active']),
            get_update_params=lambda r: (r['is_active'], r['item_id'], r['quiz_id'])
        )
        mysql.connection.commit()
    except Exception:
        mysql.connection.rollback()
        logger.exception("Error updating item_quiz")
        raise
    finally:
        cursor.close()

def update_questions():
    logger.info("Updating questions (soft delete)")
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        questions, choices = load_questions()

        insert_sql_q = '''
            INSERT INTO questions_catalog (
                question_id, question_type,
                min_choices, max_choices, parent_question_id,
                condition_value, is_conditional, question,
                question_category, question_description, hint,
                media_type, media_url, country_code, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        '''
        update_sql_q = '''
            UPDATE questions_catalog
            SET question_type=%s,
                min_choices=%s, max_choices=%s, parent_question_id=%s,
                condition_value=%s, is_conditional=%s, question=%s,
                question_category=%s, question_description=%s, hint=%s,
                media_type=%s, media_url=%s, country_code=%s, is_active=%s
            WHERE question_id=%s
        '''
        existing_q_sql = "SELECT question_id FROM questions_catalog"

        def get_insert_q_params(r):
            cond = json.dumps(r['condition_value']) if r['condition_value'] is not None else None
            return (
                r['question_id'], r['question_type'], r['min_choices'],
                r['max_choices'], r['parent_question_id'], cond,
                r['is_conditional'], r['question'], r['question_category'],
                r['question_description'], r['hint'], r['media_type'],
                r['media_url'], r['country_code'], r['is_active']
            )

        def get_update_q_params(r):
            cond = json.dumps(r['condition_value']) if r['condition_value'] is not None else None
            return (
                r['question_type'], r['min_choices'], r['max_choices'],
                r['parent_question_id'], cond, r['is_conditional'],
                r['question'], r['question_category'], r['question_description'],
                r['hint'], r['media_type'], r['media_url'],
                r['country_code'], r['is_active'], r['question_id']
            )

        upsert_soft_delete(
            cursor, "questions_catalog", "question_id",
            questions, insert_sql_q, update_sql_q, existing_q_sql,
            get_pk=lambda r: r[0],
            get_pk_csv=lambda r: r['question_id'],
            get_insert_params=get_insert_q_params,
            get_update_params=get_update_q_params
        )
        del questions; gc.collect()

        insert_sql_c = '''
            INSERT INTO questions_choices (
                question_id, next_question_id, choice_value, choice_text,
                choice_description, additional_info, country_code,
                choice_media_url, choice_media_type, max_character_input,
                is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        '''
        update_sql_c = '''
            UPDATE questions_choices
            SET next_question_id=%s, choice_text=%s, choice_description=%s,
                additional_info=%s, country_code=%s, choice_media_url=%s,
                choice_media_type=%s, max_character_input=%s, is_active=%s
            WHERE question_id=%s AND choice_value=%s
        '''
        existing_c_sql = "SELECT question_id, choice_value FROM questions_choices"

        def get_insert_c_params(r):
            return (
                r['question_id'], r['next_question_id'], r['choice_value'],
                r['choice_text'], r['choice_description'], r['additional_info'],
                r['country_code'], r['choice_media_url'], r['choice_media_type'],
                r['max_character_input'], r['is_active']
            )
        def get_update_c_params(r):
            return (
                r['next_question_id'], r['choice_text'], r['choice_description'],
                r['additional_info'], r['country_code'], r['choice_media_url'],
                r['choice_media_type'], r['max_character_input'], r['is_active'],
                r['question_id'], r['choice_value']
            )

        for i in range(0, len(choices), 200):
            batch = choices[i:i+200]
            upsert_soft_delete(
                cursor, "questions_choices", "(question_id,choice_value)",
                batch, insert_sql_c, update_sql_c, existing_c_sql,
                get_pk=lambda r: (r[0], r[1]),
                get_pk_csv=lambda r: (r['question_id'], r['choice_value']),
                get_insert_params=get_insert_c_params,
                get_update_params=get_update_c_params
            )
            del batch; gc.collect()

        mysql.connection.commit()
    except Exception:
        mysql.connection.rollback()
        logger.exception("Error updating questions")
        raise
    finally:
        cursor.close()

def update_quiz_questions():
    logger.info("Updating quiz_questions (soft delete)")
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        quiz_qs = load_quiz_questions()
        pack_clarte_qs = [q for q in quiz_qs if q['quiz_id'] == 'pack_clarte']
        logger.info(f"pack_clarte questions loaded from CSV: {len(pack_clarte_qs)}")
        logger.info(f"pack_clarte question_ids: {[q['question_id'] for q in pack_clarte_qs]}")
        
        insert_sql = '''
            INSERT INTO quiz_questions (
                quiz_id, question_id, question_ranking, is_active
            ) VALUES (%s, %s, %s, %s)
        '''
        update_sql = '''
            UPDATE quiz_questions
            SET question_ranking=%s, is_active=%s
            WHERE quiz_id=%s AND question_id=%s
        '''
        existing_sql = "SELECT quiz_id, question_id FROM quiz_questions"

        upsert_soft_delete(
            cursor, "quiz_questions", "(quiz_id,question_id)",
            quiz_qs, insert_sql, update_sql, existing_sql,
            get_pk=lambda r: (r[0], r[1]),
            get_pk_csv=lambda r: (r['quiz_id'], r['question_id']),
            get_insert_params=lambda r: (
                r['quiz_id'], r['question_id'], r['question_ranking'], r['is_active']
            ),
            get_update_params=lambda r: (
                r['question_ranking'], r['is_active'], r['quiz_id'], r['question_id']
            )
        )
        mysql.connection.commit()
    except Exception:
        mysql.connection.rollback()
        logger.exception("Error updating quiz_questions")
        raise
    finally:
        cursor.close()

def update_quiz_result():
    logger.info("Updating quiz_result (soft delete)")
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        results = load_quiz_result()
        
        insert_sql = '''
            INSERT INTO quiz_result (
                quiz_id, result_step_id, result_step_ranking,
                template_html, prompt_system, prompt_instruction, prompt_knowledge,
                validation_criteria,
                is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        '''
        
        update_sql = '''
            UPDATE quiz_result
            SET result_step_ranking=%s, template_html=%s,
                prompt_system=%s, prompt_instruction=%s,
                prompt_knowledge=%s, validation_criteria=%s, is_active=%s
            WHERE quiz_id=%s AND result_step_id=%s
        '''
        
        existing_sql = "SELECT quiz_id, result_step_id FROM quiz_result"
        
        upsert_soft_delete(
            cursor, "quiz_result", "(quiz_id,result_step_id)",
            results, insert_sql, update_sql, existing_sql,
            get_pk=lambda r: (r[0], r[1]),
            get_pk_csv=lambda r: (r['quiz_id'], r['result_step_id']),
            get_insert_params=lambda r: (
                r['quiz_id'], r['result_step_id'], r['result_step_ranking'],
                r['template_html'], r['prompt_system'], r['prompt_instruction'],
                r['prompt_knowledge'], r['validation_criteria'], r['is_active']
            ),
            get_update_params=lambda r: (
                r['result_step_ranking'], r['template_html'],
                r['prompt_system'], r['prompt_instruction'],
                r['prompt_knowledge'], r['validation_criteria'], r['is_active'],
                r['quiz_id'], r['result_step_id']
            )
        )
        mysql.connection.commit()
    except Exception:
        mysql.connection.rollback()
        logger.exception("Error updating quiz_result")
        raise
    finally:
        cursor.close()

def enrich_products_with_features(products: List[Dict[str, Any]], features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Enrichit les produits avec leurs caractéristiques pour l'affichage dans le shop"""
    features_by_product: Dict[str, List[Dict[str, Any]]] = {}
    for f in features:
        if not f.get('is_active', True):
            continue
        pid = f['product_id']
        features_by_product.setdefault(pid, []).append({
            "icon": f['feature_icon'],
            "text": f['feature_text'],
            "order": f['feature_order']
        })
    for pid, feats in features_by_product.items():
        feats.sort(key=lambda x: x['order'])
    for p in products:
        pid = p['product_id']
        if pid in features_by_product:
            p['features'] = [{"icon": f['icon'], "text": f['text']} for f in features_by_product[pid]]
    return products

def get_shop_products() -> List[Dict[str, Any]]:
    """Récupère les produits avec toutes leurs caractéristiques pour le shop"""
    try:
        products = load_product_catalog()
        features = load_product_features()
        result = enrich_products_with_features(products, features)
        del products, features; gc.collect()
        return result
    except Exception:
        logger.exception("Error getting shop products")
        raise

def update_database():
    """Update all CSV-based tables (soft delete approach) with memory optimization."""
    logger.info("Starting database update (soft delete)")
    try:
        update_quiz_catalog();       gc.collect()
        update_products();           gc.collect()  # Cette fonction met à jour product_catalog_items
        update_product_features();   gc.collect()
        update_questions();          gc.collect()
        update_quiz_questions();     gc.collect()
        update_quiz_result();        gc.collect()
        update_item_quiz();          gc.collect()  # Déplacez cette fonction après que toutes les tables nécessaires soient mises à jour
        logger.info("Database update completed successfully (soft delete).")
    except Exception:
        logger.exception("Error during database update")
        raise
