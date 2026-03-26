import logging
from flask import current_app
logger = logging.getLogger(__name__)

def init_db(force_init=False):
    """Initialise la base de données seulement si nécessaire ou si forcé"""
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()

    try:
        cursor.execute("SHOW TABLES LIKE 'users'")
        tables_exist = cursor.fetchone() is not None

        if tables_exist and not force_init:
            logger.info("Database already initialized, skipping schema creation")
            return

        logger.info("Initializing and optimizing database...")

        queries = [
            '''
            /*
            Database Schema Organization:

            Section 1: Core User Management
            - User data, authentication, and profile information
            - Manages user accounts and personal details

            Section 2: Product Management
            - Products, items, and their relationships
            - Manages catalog, pricing, and product configurations
            - Handles multilingual product information

            Section 3: Quiz Management
            - Quiz definitions, questions, and choices
            - Manages quiz content and structure
            - Handles multilingual quiz content

            Section 4: Transaction Management
            - Orders, payments, and pricing details
            - Handles financial transactions and pricing
            - Manages discounts and coupons

            Section 5: Linking Tables
            - Connects products, items, and quizzes
            - Tracks sessions and user answers
            - Manages access tokens and permissions
            */

            -- Section 1: Core User Management
            CREATE TABLE IF NOT EXISTS users (
                user_id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Unique identifier for each user',
                username VARCHAR(80) NULL COMMENT 'Unique username for each user',
                firstname VARCHAR(50) NULL COMMENT 'Prénom de l utilisateur',
                lastname VARCHAR(50) NULL COMMENT 'Nom de famille de l utilisateur',
                password VARCHAR(255) COMMENT 'Hashed password for authentication (NULL for OAuth users)',
                email VARCHAR(120) UNIQUE NOT NULL COMMENT 'Unique email address',
                country_code CHAR(2) NOT NULL DEFAULT 'FR' COMMENT 'User country code',
                user_status ENUM('lead', 'free_user', 'user', 'admin', 'coach') NOT NULL DEFAULT 'user' COMMENT 'Type d utilisateur (lead: prospect, customer: client, admin: administrateur, coach:coach)',
                two_factor_secret VARCHAR(64) NULL COMMENT '2FA secret key',
                access_token VARCHAR(100) NULL UNIQUE COMMENT 'Token d accès unique pour accéder aux ressources utilisateur',
                last_login DATETIME NULL COMMENT 'Last login timestamp',
                profile_picture VARCHAR(255) NULL COMMENT 'Profile picture URL',
                phone_number VARCHAR(20) NULL COMMENT 'Contact phone number',
                address VARCHAR(255) NULL COMMENT 'Physical address',
                newsletter_subscription BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Newsletter subscription status',
                partner_consent BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Consentement pour être contacté par les partenaires',
                lead_source VARCHAR(50) NULL COMMENT 'Source du lead (homepage, social, referral, etc.)',
                lead_status ENUM('new', 'contacted', 'qualified', 'converted', 'lost') NULL COMMENT 'Statut du lead dans le processus de conversion',
                lead_interest VARCHAR(100) NULL COMMENT 'Centre d intérêt principal du lead',
                nb_accompagnement VARCHAR(20) NULL COMMENT 'Nombre de personnes accompagnées par mois (pour les coachs)',
                lead_notes TEXT NULL COMMENT 'Notes sur le lead',
                onboarding_stage ENUM('invited', 'email_verified', 'profile_created', 'completed') NULL COMMENT 'Étape du processus d onboarding',
                invite_token VARCHAR(100) NULL UNIQUE COMMENT 'Token d invitation unique',
                invite_expiry DATETIME NULL COMMENT 'Date d expiration du token dinvitation',
                last_contacted DATETIME NULL COMMENT 'Date du dernier contact avec le lead',
                privacy_policy_accepted BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Privacy policy acceptance',
                is_google_user BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Google authentication status',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',
                INDEX idx_username (username),
                INDEX idx_email (email),
                INDEX idx_firstname (firstname),
                INDEX idx_lastname (lastname),
                INDEX idx_country_code (country_code),
                INDEX idx_user_status (user_status),
                INDEX idx_lead_status (lead_status),
                INDEX idx_lead_source (lead_source),
                INDEX idx_nb_accompagnement (nb_accompagnement),
                INDEX idx_onboarding_stage (onboarding_stage),
                INDEX idx_invite_token (invite_token),
                INDEX idx_access_token (access_token)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Core user account and profile management';
            ''',
            '''
            -- Section 2: Quiz Management
            CREATE TABLE IF NOT EXISTS quiz_catalog (
                quiz_id VARCHAR(100) PRIMARY KEY COMMENT 'Unique quiz identifier',
                quiz_type VARCHAR(100) NOT NULL COMMENT 'Quiz type (e.g., profiling, assessment)',
                description TEXT COMMENT 'Detailed quiz description',
                short_description VARCHAR(255) COMMENT 'Brief quiz description for display',
                image_url VARCHAR(255) COMMENT 'Quiz image URL',
                quiz_category VARCHAR(100) COMMENT 'Quiz category classification',
                questions_count INT DEFAULT 0 COMMENT 'Total number of questions in quiz',
                is_active BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Quiz availability status',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',
                INDEX idx_quiz_type (quiz_type),
                INDEX idx_quiz_category (quiz_category),
                INDEX idx_is_active (is_active)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Quiz catalog and configuration management';
            ''',
            '''
            -- Section 3: Product Management
            CREATE TABLE IF NOT EXISTS product_catalog (
                product_id VARCHAR(100) PRIMARY KEY COMMENT 'Unique product identifier',
                product_name VARCHAR(255) NOT NULL COMMENT 'Commercial product name',
                product_type VARCHAR(100) NOT NULL COMMENT 'Product type (e.g., single_quiz, bundle)',
                description TEXT COMMENT 'Detailed product description',
                short_description VARCHAR(255) COMMENT 'Brief product description for display',
                emoji VARCHAR(10) NULL COMMENT 'Emoji représentant le produit',
                subtitle VARCHAR(255) NULL COMMENT 'Sous-titre du produit',
                is_featured BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Produit mis en avant',
                button_text VARCHAR(100) NULL COMMENT 'Texte du bouton d action',
                image_url VARCHAR(255) COMMENT 'Product image URL',
                product_category VARCHAR(100) COMMENT 'Product category classification',
                base_price INT NOT NULL COMMENT 'Unit Base price in cents (before tax)',
                vat_price INT NOT NULL COMMENT 'Unit VAT amount in cents',
                unit_amount INT NOT NULL COMMENT 'Unit price in cents (for Stripe integration) (base + VAT)',
                vat_rate DECIMAL(4,2) NOT NULL DEFAULT 20.00 COMMENT 'VAT rate percentage',
                currency VARCHAR(10) NOT NULL DEFAULT 'eur' COMMENT 'Currency code',
                is_active BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Product availability status',
                country_code CHAR(2) NOT NULL DEFAULT 'FR' COMMENT 'Product country code',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',
                INDEX idx_product_type (product_type),
                INDEX idx_product_category (product_category),
                INDEX idx_is_active (is_active),
                INDEX idx_country_code (country_code)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Product catalog and pricing management';
            ''',
            '''
            CREATE TABLE IF NOT EXISTS product_catalog_items (
                item_id VARCHAR(100) PRIMARY KEY COMMENT 'Unique item identifier',
                item_name VARCHAR(255) NOT NULL COMMENT 'Technical item name',
                item_type VARCHAR(100) NOT NULL COMMENT 'Item type (e.g., quiz, course)',
                description TEXT COMMENT 'Detailed item description',
                image_url VARCHAR(255) COMMENT 'Item image URL',
                item_category VARCHAR(100) COMMENT 'Item category classification',
                base_price INT NOT NULL COMMENT 'Unit Base price in cents (before tax)',
                vat_price INT NOT NULL COMMENT 'Unit VAT amount in cents',
                unit_amount INT NOT NULL COMMENT 'Unit price in cents (for Stripe integration)(base + VAT)',
                vat_rate DECIMAL(4,2) NOT NULL DEFAULT 20.00 COMMENT 'VAT rate percentage',
                currency VARCHAR(10) NOT NULL DEFAULT 'eur' COMMENT 'Currency code',
                is_active BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Item availability status',
                country_code CHAR(2) NOT NULL DEFAULT 'FR' COMMENT 'Item country code',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',
                INDEX idx_item_type (item_type),
                INDEX idx_item_category (item_category),
                INDEX idx_is_active (is_active),
                INDEX idx_country_code (country_code)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Product components catalog';
            ''',
            '''
            -- Création d'une table pour les caractéristiques des produits
            CREATE TABLE IF NOT EXISTS product_features (
                product_id VARCHAR(100) NOT NULL COMMENT 'Identifiant du produit',
                feature_order INT NOT NULL COMMENT 'Ordre d affichage de la caractéristique',
                feature_icon VARCHAR(10) NOT NULL COMMENT 'Icône de la caractéristique',
                feature_text TEXT NOT NULL COMMENT 'Description de la caractéristique',
                is_active BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Statut de la caractéristique',
                PRIMARY KEY (product_id, feature_order),
                FOREIGN KEY (product_id) REFERENCES product_catalog(product_id) ON DELETE CASCADE,
                INDEX idx_product_id (product_id)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Caractéristiques des produits pour l affichage dans le shop';
            ''',
            '''
            -- Section 4: Transaction Management
            CREATE TABLE IF NOT EXISTS orders (
                order_id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Unique order identifier',
                order_number VARCHAR(20) UNIQUE NOT NULL COMMENT 'Alphanumeric order number',
                user_id INT NULL COMMENT 'Customer identifier (NULL if user deleted)',  -- ✅ CHANGÉ: NOT NULL → NULL
                stripe_session_id VARCHAR(255) UNIQUE NULL COMMENT 'Stripe checkout session ID',
                base_amount INT NOT NULL COMMENT 'Base amount in cents (before tax)',
                vat_amount INT NOT NULL COMMENT 'VAT amount in cents',
                order_amount INT NOT NULL COMMENT 'Total order amount in cents',
                origin_order_amount INT NOT NULL COMMENT 'Original order amount before discounts',
                discount_amount INT NOT NULL DEFAULT 0 COMMENT 'Discount amount in cents',
                currency VARCHAR(10) NOT NULL DEFAULT 'EUR' COMMENT 'Currency code',
                status ENUM('pending', 'paid', 'failed') NOT NULL DEFAULT 'pending' COMMENT 'Order status',
                postcode VARCHAR(255) COMMENT 'Delivery postcode',
                payment_method VARCHAR(100) COMMENT 'Payment method used',
                notes TEXT COMMENT 'Additional order notes',
                discount_code VARCHAR(50) COMMENT 'Applied discount code',
                country_code CHAR(2) NOT NULL DEFAULT 'FR' COMMENT 'Order country code',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL,  -- ✅ CHANGÉ: CASCADE → SET NULL
                INDEX idx_user_id (user_id),
                INDEX idx_status (status),
                INDEX idx_country_code (country_code)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Order and payment management';
            ''',
            '''
            CREATE TABLE IF NOT EXISTS bookings (
                id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Unique booking identifier',
                booking_id VARCHAR(100) NOT NULL UNIQUE COMMENT 'External booking ID',
                user_id INT NOT NULL COMMENT 'User ID',
                product_id VARCHAR(100) NOT NULL COMMENT 'Product ID',
                booking_date DATETIME NOT NULL COMMENT 'Appointment date and time',
                end_date DATETIME NULL COMMENT 'End time of appointment',
                duration_minutes INT DEFAULT 60 COMMENT 'Duration in minutes',
                attendee_email VARCHAR(255) NULL COMMENT 'Attendee email',
                attendee_name VARCHAR(255) NULL COMMENT 'Attendee name',
                booking_answers JSON NULL COMMENT 'Form responses',
                status VARCHAR(50) DEFAULT 'confirmed' COMMENT 'Booking status',
                zoom_link TEXT NULL COMMENT 'Zoom meeting link',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX (user_id, product_id),
                INDEX (booking_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES product_catalog(product_id) ON DELETE CASCADE
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Booking management table';
            ''',
            '''
            -- Create the product_status table if it doesn't already exist
            CREATE TABLE product_status (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                order_id INT NOT NULL, 
                product_id VARCHAR(100) NOT NULL,
                status VARCHAR(50) NOT NULL,
                booking_id INT NULL,
                livrable_date DATETIME NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                
                -- Clés étrangères
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE,  
                FOREIGN KEY (product_id) REFERENCES product_catalog(product_id) ON DELETE CASCADE,
                FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE SET NULL,
                
                -- Index pour performances
                INDEX idx_user_id (user_id),
                INDEX idx_order_id (order_id),
                INDEX idx_product_id (product_id),
                INDEX idx_booking_id (booking_id),
                INDEX idx_status (status),
                INDEX idx_user_product (user_id, product_id)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Current status of each purchased product';
            ''',
            '''
            -- Create the product_status_updates table if it doesn't already exist
            CREATE TABLE IF NOT EXISTS product_status_updates (
                id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Primary key for status updates',
                order_id INT NOT NULL COMMENT 'ID of the corresponding product_status record',
                user_id INT NOT NULL COMMENT 'ID of the user concerned',
                product_id VARCHAR(100) NOT NULL COMMENT 'ID of the product concerned',
                old_status VARCHAR(50) NULL COMMENT 'Previous status (NULL if first status)',
                new_status VARCHAR(50) NOT NULL COMMENT 'New status',
                booking_id INT NULL COMMENT 'Reference to booking if the update involves an appointment',
                admin_id INT NULL COMMENT 'ID of the admin who performed the update (if applicable)',
                admin_note TEXT NULL COMMENT 'Administrative note (visible to admins only)',
                update_type ENUM('auto', 'manual', 'system') NOT NULL DEFAULT 'auto' COMMENT 'Type of update',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Update creation timestamp',
                FOREIGN KEY (order_id) REFERENCES product_status(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES product_catalog(product_id) ON DELETE CASCADE,
                FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE SET NULL,
                FOREIGN KEY (admin_id) REFERENCES users(user_id) ON DELETE SET NULL
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'History of all status changes for purchased products';
            ''',
            '''
            CREATE TABLE IF NOT EXISTS coupons (
                coupon_code VARCHAR(50) PRIMARY KEY COMMENT 'Unique coupon code',
                product_id VARCHAR(100) NOT NULL COMMENT 'Associated product identifier',
                description TEXT COMMENT 'Coupon description',
                stripe_coupon_id VARCHAR(255) UNIQUE NULL COMMENT 'Stripe coupon identifier',
                discount_type ENUM('percentage', 'fixed') NOT NULL COMMENT 'Discount type',
                discount_value INT NOT NULL COMMENT 'Discount amount in cents',
                usage_limit_per_user INT DEFAULT 1 COMMENT 'Maximum uses per user',
                min_purchase_amount INT DEFAULT NULL COMMENT 'Minimum purchase amount in cents',
                country_code CHAR(2) NOT NULL DEFAULT 'FR' COMMENT 'Coupon country code',
                max_uses INT DEFAULT 1 COMMENT 'Maximum total uses',
                current_uses INT DEFAULT 0 COMMENT 'Current total uses',
                start_date TIMESTAMP NULL COMMENT 'Validity start date',
                end_date TIMESTAMP NULL COMMENT 'Validity end date',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',
                FOREIGN KEY (product_id) REFERENCES product_catalog(product_id) ON DELETE CASCADE,
                INDEX idx_product_id (product_id),
                INDEX idx_country_code (country_code),
                INDEX idx_stripe_coupon_id (stripe_coupon_id)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Coupon and discount management';
            ''',
            '''
            CREATE TABLE IF NOT EXISTS order_product (
                order_id INT NOT NULL COMMENT 'Order identifier',
                product_id VARCHAR(100) NOT NULL COMMENT 'Product identifier',
                quantity INT NOT NULL DEFAULT 1 COMMENT 'Product quantity',
                unit_price INT NOT NULL COMMENT 'Unit price in cents',
                base_amount INT NOT NULL COMMENT 'Base amount in cents',
                vat_amount INT NOT NULL COMMENT 'VAT amount in cents',
                vat_rate DECIMAL(4,2) NOT NULL COMMENT 'VAT rate percentage',
                product_amount INT NOT NULL COMMENT 'Total product amount in cents',
                origin_product_amount INT NOT NULL COMMENT 'Original product amount before discounts',
                discount_amount INT NOT NULL DEFAULT 0 COMMENT 'Discount amount in cents',
                currency VARCHAR(10) NOT NULL DEFAULT 'EUR' COMMENT 'Currency code',
                country_code CHAR(2) NOT NULL DEFAULT 'FR' COMMENT 'Order country code',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                PRIMARY KEY (order_id, product_id),
                FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES product_catalog(product_id) ON DELETE CASCADE,
                INDEX idx_order_id (order_id),
                INDEX idx_product_id (product_id),
                INDEX idx_country_code (country_code)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Order-product relationship and pricing details';
            ''',
            '''
            CREATE TABLE IF NOT EXISTS order_item (
                order_id INT NOT NULL COMMENT 'Order identifier',
                product_id VARCHAR(100) NOT NULL COMMENT 'Product identifier',
                item_id VARCHAR(100) NOT NULL COMMENT 'Item identifier',
                quantity INT NOT NULL DEFAULT 1 COMMENT 'Item quantity',
                unit_price INT NOT NULL COMMENT 'Unit price in cents',
                base_amount INT NOT NULL COMMENT 'Base amount in cents',
                vat_amount INT NOT NULL COMMENT 'VAT amount in cents',
                vat_rate DECIMAL(4,2) NOT NULL COMMENT 'VAT rate percentage',
                item_amount INT NOT NULL COMMENT 'Total item amount in cents',
                currency VARCHAR(10) NOT NULL DEFAULT 'EUR' COMMENT 'Currency code',
                country_code CHAR(2) NOT NULL DEFAULT 'FR' COMMENT 'Order country code',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                PRIMARY KEY (order_id, product_id, item_id),
                FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES product_catalog(product_id) ON DELETE CASCADE,
                FOREIGN KEY (item_id) REFERENCES product_catalog_items(item_id) ON DELETE CASCADE,
                INDEX idx_order_id (order_id),
                INDEX idx_product_id (product_id),
                INDEX idx_item_id (item_id),
                INDEX idx_country_code (country_code)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Order-item relationship and pricing details';
            ''',
            '''
            -- Section 5: Product and Quiz Management
            CREATE TABLE IF NOT EXISTS product_items (
                product_id VARCHAR(100) NOT NULL COMMENT 'Product identifier',
                item_id VARCHAR(100) NOT NULL COMMENT 'Item identifier',
                quantity INT NOT NULL DEFAULT 1 COMMENT 'Item quantity in product',
                country_code CHAR(2) NOT NULL DEFAULT 'FR' COMMENT 'Relationship country code',
                is_active BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Relationship status',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                PRIMARY KEY (product_id, item_id),
                FOREIGN KEY (product_id) REFERENCES product_catalog(product_id) ON DELETE CASCADE,
                FOREIGN KEY (item_id) REFERENCES product_catalog_items(item_id) ON DELETE CASCADE,
                INDEX idx_product (product_id),
                INDEX idx_item (item_id),
                INDEX idx_country_code (country_code)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Product to item relationship mapping';
            ''',
            '''
            CREATE TABLE IF NOT EXISTS item_quiz (
                item_id VARCHAR(100) NOT NULL COMMENT 'Item identifier',
                quiz_id VARCHAR(100) NOT NULL COMMENT 'Quiz identifier',
                is_active BOOLEAN DEFAULT TRUE COMMENT 'Relationship status',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                PRIMARY KEY (item_id, quiz_id),
                FOREIGN KEY (item_id) REFERENCES product_catalog_items(item_id) ON DELETE CASCADE,
                FOREIGN KEY (quiz_id) REFERENCES quiz_catalog(quiz_id) ON DELETE CASCADE,
                INDEX idx_item_id (item_id),
                INDEX idx_quiz_id (quiz_id),
                INDEX idx_is_active (is_active)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Item to quiz relationship mapping';
            ''',
            '''
            CREATE TABLE IF NOT EXISTS questions_catalog (
                question_id INT PRIMARY KEY COMMENT 'Unique question identifier',
                question TEXT COMMENT 'Question text',
                question_description TEXT COMMENT 'Detailed question description',
                question_category VARCHAR(100) COMMENT 'Question category',
                hint TEXT COMMENT 'Question hint or help text',
                media_type VARCHAR(50) COMMENT 'Associated media type',
                media_url TEXT COMMENT 'Media resource URL',
                country_code CHAR(2) NOT NULL COMMENT 'Question country code',
                question_type ENUM('select', 'multi_select', 'free_text', 'ranking', 'location') 
                    NOT NULL DEFAULT 'select' COMMENT 'Question type',
                max_choices INT DEFAULT NULL COMMENT 'Maximum choices for multi-select',
                min_choices INT DEFAULT NULL COMMENT 'Minimum choices for multi-select',
                parent_question_id INT DEFAULT NULL COMMENT 'Parent question for conditional logic',
                condition_value JSON DEFAULT NULL COMMENT 'Conditional trigger values',
                is_conditional BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Conditional question flag',
                is_active BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Question active status',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',
                INDEX idx_question_category (question_category),
                INDEX idx_question_type (question_type),
                INDEX idx_country_code (country_code),
                INDEX idx_parent_question (parent_question_id),
                INDEX idx_is_active (is_active),
                FOREIGN KEY (parent_question_id) REFERENCES questions_catalog(question_id) ON DELETE SET NULL
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Question bank and configuration';
            ''',
            '''
            CREATE TABLE IF NOT EXISTS quiz_questions (
                quiz_id VARCHAR(100) NOT NULL COMMENT 'Quiz identifier',
                question_id INT NOT NULL COMMENT 'Question identifier',
                question_ranking INT NOT NULL COMMENT 'Question display order',
                country_code CHAR(2) NOT NULL DEFAULT 'FR' COMMENT 'Relationship country code',
                is_active BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Relationship status',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',
                PRIMARY KEY (quiz_id, question_id),
                FOREIGN KEY (quiz_id) REFERENCES quiz_catalog(quiz_id) ON DELETE CASCADE,
                FOREIGN KEY (question_id) REFERENCES questions_catalog(question_id) ON DELETE CASCADE,
                INDEX idx_question_id (question_id),
                INDEX idx_country_code (country_code)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Quiz to question relationship mapping';
            ''',
            '''
            CREATE TABLE IF NOT EXISTS questions_choices (
                question_id INT NOT NULL COMMENT 'Question identifier',
                next_question_id INT DEFAULT NULL COMMENT 'Next question identifier based on this choice',
                choice_value INT NOT NULL COMMENT 'Choice identifier',
                choice_text TEXT COMMENT 'Choice text content',
                choice_description TEXT COMMENT 'Detailed choice description',
                additional_info TEXT COMMENT 'Additional choice information',
                max_character_input INT DEFAULT NULL COMMENT 'Character limit for text input',
                country_code CHAR(2) NOT NULL COMMENT 'Choice country code',
                choice_media_url TEXT COMMENT 'Media resource URL',
                choice_media_type VARCHAR(50) COMMENT 'Media type',
                is_active BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Choice active status',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',
                PRIMARY KEY (question_id, choice_value),
                FOREIGN KEY (question_id) REFERENCES questions_catalog(question_id) ON DELETE CASCADE,
                INDEX idx_country_code (country_code),
                INDEX idx_position (choice_value),
                INDEX idx_is_active (is_active)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Question choices and configuration';
            ''',
            '''
            CREATE TABLE IF NOT EXISTS quiz_user (
                quiz_session_id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Unique session identifier',
                quiz_id VARCHAR(100) NOT NULL COMMENT 'Quiz identifier',
                user_id INT NOT NULL COMMENT 'User identifier',
                start_time DATETIME DEFAULT NULL COMMENT 'Session start time',
                end_time DATETIME DEFAULT NULL COMMENT 'Session end time',
                current_question_id INT DEFAULT NULL COMMENT 'Current active question',
                question_history JSON NULL COMMENT 'Question history in JSON format',
                session_duration INT DEFAULT NULL COMMENT 'Session duration in seconds',
                questions_answered_count INT DEFAULT 0 COMMENT 'Questions answered count',
                quiz_status ENUM('not_started', 'in_progress', 'answers_review', 'completed')
                    NOT NULL DEFAULT 'not_started' COMMENT 'Session status',
                country_code CHAR(2) NOT NULL DEFAULT 'FR' COMMENT 'Session country code',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',
                FOREIGN KEY (quiz_id) REFERENCES quiz_catalog(quiz_id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (current_question_id) REFERENCES questions_catalog(question_id) ON DELETE SET NULL,
                INDEX idx_user_id (user_id),
                INDEX idx_quiz_id (quiz_id),
                INDEX idx_quiz_status (quiz_status),
                INDEX idx_country_code (country_code)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Quiz session tracking and management';
            ''',
            '''
            CREATE TABLE IF NOT EXISTS answer_user (
                quiz_session_id INT NOT NULL COMMENT 'Session identifier',
                question_id INT NOT NULL COMMENT 'Question identifier',
                answer_value JSON COMMENT 'Answer data in JSON format',
                answer_text TEXT COMMENT 'Text answer content',
                country_code CHAR(2) NOT NULL DEFAULT 'FR' COMMENT 'Answer country code',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',
                PRIMARY KEY (quiz_session_id, question_id),
                FOREIGN KEY (quiz_session_id) REFERENCES quiz_user(quiz_session_id) ON DELETE CASCADE,
                FOREIGN KEY (question_id) REFERENCES questions_catalog(question_id) ON DELETE CASCADE,
                INDEX idx_question_id (question_id),
                INDEX idx_country_code (country_code)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'User answer storage and tracking';
            ''',
            '''
            -- Create table for storing prompt history
            CREATE TABLE IF NOT EXISTS prompt_user (
                prompt_id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Unique identifier for each prompt',
                result_id VARCHAR(100) NOT NULL COMMENT 'Analysis identifier',
                result_step_id VARCHAR(100) NOT NULL COMMENT 'Step identifier',
                user_id INT NOT NULL COMMENT 'User ID who generated the prompt',
                prompt LONGTEXT NOT NULL COMMENT 'Full prompt content',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',
                INDEX idx_result_composite (result_id, result_step_id) COMMENT 'Index for result lookup',
                INDEX idx_user_id (user_id) COMMENT 'Index for user lookup',
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Prompt history tracking and management';
            ''',
             '''
            CREATE TABLE IF NOT EXISTS tokens (
                token_code VARCHAR(255) PRIMARY KEY COMMENT 'Unique token identifier',
                user_id INT COMMENT 'Associated user identifier',
                product_id VARCHAR(100) NULL COMMENT 'Associated product identifier',
                item_id VARCHAR(100) NULL COMMENT 'Associated item identifier',
                quiz_id VARCHAR(100) NOT NULL COMMENT 'Associated quiz identifier',
                order_id INT NULL COMMENT 'Associated order identifier',
                coupon_code VARCHAR(50) NULL COMMENT 'Code du coupon utilisé',
                description TEXT COMMENT 'Token description',
                country_code CHAR(2) NOT NULL DEFAULT 'FR' COMMENT 'Token country code',
                token_type ENUM('free', 'paid') NOT NULL DEFAULT 'paid' COMMENT 'Token type',
                is_used BOOLEAN DEFAULT FALSE COMMENT 'Usage status',
                used_at DATETIME DEFAULT NULL COMMENT 'Usage timestamp',
                used_for_piste INT NULL COMMENT 'Piste identifier for which the token was used',
                expiration_date TIMESTAMP NULL COMMENT 'Expiration timestamp',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',
                INDEX idx_user_token (user_id),
                INDEX idx_country_code (country_code),
                INDEX idx_order_id (order_id),
                INDEX idx_token_type (token_type),
                INDEX idx_product_id (product_id),
                INDEX idx_item_id (item_id),
                INDEX idx_quiz_id (quiz_id),
                INDEX idx_coupon_code (coupon_code),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL,
                FOREIGN KEY (product_id) REFERENCES product_catalog(product_id) ON DELETE CASCADE,
                FOREIGN KEY (item_id) REFERENCES product_catalog_items(item_id) ON DELETE CASCADE,
                FOREIGN KEY (quiz_id) REFERENCES quiz_catalog(quiz_id) ON DELETE CASCADE,
                FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE SET NULL,
                FOREIGN KEY (coupon_code) REFERENCES coupons(coupon_code) ON DELETE SET NULL
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Access token management and tracking';
            ''',
            '''
            CREATE TABLE IF NOT EXISTS result_user (
                quiz_id VARCHAR(100) NOT NULL COMMENT 'Associated quiz identifier',
                user_id INT NOT NULL COMMENT 'User identifier',
                result_id VARCHAR(100) NOT NULL COMMENT 'Unique analysis identifier',
                result_step_id VARCHAR(100) NOT NULL COMMENT 'Step result identifier (e.g., vision_360, checkup_pro)',
                generator_type ENUM('user', 'admin') NOT NULL DEFAULT 'user' COMMENT 'Indicates who generated the analysis (user or admin)',
                is_active BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Whether this result is currently active',
                result_json JSON NOT NULL COMMENT 'LLM response data',
                token_id VARCHAR(255) NOT NULL COMMENT 'Associated token for the analysis',
                prompt_id INT NOT NULL COMMENT 'Associated prompt identifier',
                generation_time_seconds DECIMAL(6,2) NULL COMMENT 'Total generation time in seconds (including API call)',
                api_call_time_seconds DECIMAL(6,2) NULL COMMENT 'API call duration in seconds',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                PRIMARY KEY (result_id, result_step_id, generator_type),
                FOREIGN KEY (quiz_id) REFERENCES quiz_catalog(quiz_id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (token_id) REFERENCES tokens(token_code) ON DELETE CASCADE,
                FOREIGN KEY (prompt_id) REFERENCES prompt_user(prompt_id) ON DELETE CASCADE,
                INDEX idx_quiz_id (quiz_id),
                INDEX idx_user_id (user_id),
                INDEX idx_result_id (result_id),
                INDEX idx_token_id (token_id),
                INDEX idx_prompt_id (prompt_id),
                INDEX idx_is_active (is_active)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'User analysis results storage and tracking';
            ''',
            '''
            CREATE TABLE IF NOT EXISTS async_analysis_jobs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                
                -- Identifiants
                job_uuid VARCHAR(36) NOT NULL UNIQUE COMMENT 'UUID unique pour identifier le job',
                user_id INT NOT NULL COMMENT 'Utilisateur pour qui l''analyse est générée',
                quiz_id VARCHAR(50) NOT NULL COMMENT 'Quiz concerné',
                result_id VARCHAR(36) NULL COMMENT 'UUID de l''analyse (généré au démarrage)',
                step_id VARCHAR(50) NOT NULL DEFAULT 'career_path_v2' COMMENT 'Étape d''analyse',
                order_id INT NULL COMMENT 'Commande associée (optionnel)',
                
                -- Contexte de génération
                generator_type ENUM('user', 'admin') NOT NULL DEFAULT 'admin' COMMENT 'Type de générateur',
                created_by_admin_id INT NULL COMMENT 'Admin qui a lancé le job (si applicable)',
                
                -- Statut du job
                job_status ENUM('pending', 'processing', 'completed', 'error', 'cancelled') NOT NULL DEFAULT 'pending',
                
                -- Paramètres de génération (stockés en JSON)
                generation_params JSON NULL COMMENT 'Paramètres: system_prompt, instructions, knowledge, validation_criteria',
                
                -- Cloud Tasks
                cloud_task_name VARCHAR(255) NULL COMMENT 'Nom complet de la tâche Cloud Tasks',
                cloud_task_queue VARCHAR(100) NULL DEFAULT 'analysis-generation' COMMENT 'Queue Cloud Tasks',
                
                -- Timestamps
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                started_at DATETIME NULL COMMENT 'Début de la génération',
                completed_at DATETIME NULL COMMENT 'Fin de la génération',
                
                -- Résultats et erreurs
                error_message TEXT NULL COMMENT 'Message d''erreur si échec',
                error_details JSON NULL COMMENT 'Détails de l''erreur (stacktrace, etc.)',
                
                -- Métriques de génération
                generation_time_seconds DECIMAL(10,2) NULL COMMENT 'Durée totale de génération',
                validation_attempts INT NULL DEFAULT 0 COMMENT 'Nombre de tentatives de validation',
                validation_status ENUM('pending', 'success', 'failed') NULL DEFAULT 'pending',
                
                -- Notification
                notification_sent BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Email de notification envoyé',
                notification_sent_at DATETIME NULL,
                
                -- Index pour les requêtes fréquentes
                INDEX idx_user_id (user_id),
                INDEX idx_quiz_id (quiz_id),
                INDEX idx_job_status (job_status),
                INDEX idx_created_at (created_at),
                INDEX idx_user_quiz_status (user_id, quiz_id, job_status),
                
                -- Contraintes
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (created_by_admin_id) REFERENCES users(user_id) ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            ''',
            '''
            -- Create table for quiz result configuration
            CREATE TABLE IF NOT EXISTS quiz_result (
                quiz_id VARCHAR(100) NOT NULL COMMENT 'Associated quiz identifier',
                result_step_id VARCHAR(100) NOT NULL COMMENT 'Step result identifier (e.g., vision_360, checkup_pro)',
                result_step_ranking INT NOT NULL COMMENT 'Result step display order',
                template_html VARCHAR(255) NOT NULL COMMENT 'HTML template filename',
                prompt_system TEXT COMMENT 'System prompt configuration',
                prompt_instruction TEXT NOT NULL COMMENT 'Prompt instructions',
                prompt_knowledge TEXT COMMENT 'Additional prompt context information',
                validation_criteria TEXT COMMENT 'Critères de validation pour le LLM validateur (remplace le hardcode dans _get_validation_criteria)',
                is_active BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Result configuration status',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Record creation timestamp',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Last update timestamp',
                PRIMARY KEY (quiz_id, result_step_id),
                FOREIGN KEY (quiz_id) REFERENCES quiz_catalog(quiz_id) ON DELETE CASCADE,
                INDEX idx_quiz_id (quiz_id),
                INDEX idx_result_step_id (result_step_id),
                INDEX idx_is_active (is_active)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Quiz result configuration and prompt mapping';
            ''',
            '''
            CREATE TABLE IF NOT EXISTS stripe_events (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                stripe_event_id VARCHAR(255) NOT NULL UNIQUE,
                event_type VARCHAR(100) NOT NULL,
                status ENUM('processing', 'completed', 'error') NOT NULL,
                created_at TIMESTAMP NOT NULL,
                processed_at TIMESTAMP NULL,
                error TEXT NULL,
                retry_count INT DEFAULT 0,
                INDEX idx_stripe_event_id (stripe_event_id),
                INDEX idx_status (status)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Stripe event tracking';
            ''',
            '''
            -- Table pour stocker les capsules audio
            CREATE TABLE IF NOT EXISTS capsules (
                capsule_id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Identifiant unique de la capsule',
                title VARCHAR(255) NOT NULL COMMENT 'Titre de la capsule audio',
                description TEXT COMMENT 'Description de la capsule',
                personalized_reflection TEXT NULL COMMENT 'Réflexion personnalisée affichée en fin d’écoute',
                file_name VARCHAR(255) NOT NULL COMMENT 'Nom du fichier dans le bucket',
                duration VARCHAR(10) COMMENT 'Durée de la capsule (format MM:SS)',
                capsule_order INT DEFAULT 1 COMMENT 'Ordre d''affichage de la capsule',
                is_active BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Statut d''activation de la capsule',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Date de création',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Date de mise à jour'
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Stockage des métadonnées des capsules audio';
            ''',
            '''    
            -- Table pour associer les capsules aux utilisateurs avec des tokens d'accès
            CREATE TABLE IF NOT EXISTS user_capsules (
                id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Identifiant unique de l''association',
                user_id INT NOT NULL COMMENT 'Identifiant de l''utilisateur',
                capsule_id INT NOT NULL COMMENT 'Identifiant de la capsule audio',
                sequence_number INT NOT NULL DEFAULT 1 COMMENT 'Position de la capsule dans la séquence de l utilisateur',
                access_token VARCHAR(255) NOT NULL UNIQUE COMMENT 'Token d''accès unique à la capsule',
                signed_url TEXT COMMENT 'URL signée pour accéder au fichier audio',
                signed_url_expiry DATETIME COMMENT 'Date d''expiration de l''URL signée',
                signed_url_duration INT DEFAULT 30 COMMENT 'Durée de validité de l''URL signée en minutes',
                is_listened BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Indique si la capsule a été écoutée',
                listen_count INT NOT NULL DEFAULT 0 COMMENT 'Nombre d''écoutes de la capsule',
                last_listened_at TIMESTAMP NULL COMMENT 'Dernière date d''écoute',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Date de création',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Date de mise à jour',
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (capsule_id) REFERENCES capsules(capsule_id) ON DELETE CASCADE,
                INDEX idx_user_id (user_id),
                INDEX idx_capsule_id (capsule_id),
                INDEX idx_access_token (access_token)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Association entre utilisateurs et capsules audio';
            ''',
            '''
            -- Table pour suivre l'historique des écoutes
            CREATE TABLE IF NOT EXISTS capsules_history (
                id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Identifiant unique de l''entrée',
                user_id INT NOT NULL COMMENT 'Identifiant de l''utilisateur',
                capsule_id INT NOT NULL COMMENT 'Identifiant de la capsule audio',
                listen_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Date d''écoute',
                duration_seconds INT DEFAULT 0 COMMENT 'Durée d''écoute en secondes',
                completion_percentage INT DEFAULT 0 COMMENT 'Pourcentage d''écoute (0-100)',
                user_agent TEXT COMMENT 'User-Agent du navigateur',
                ip_address VARCHAR(45) COMMENT 'Adresse IP (compatible IPv6)',
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (capsule_id) REFERENCES capsules(capsule_id) ON DELETE CASCADE,
                INDEX idx_user_capsule (user_id, capsule_id),
                INDEX idx_listen_date (listen_date)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            COMMENT = 'Historique des écoutes des capsules audio';
            ''',
            '''
        CREATE TABLE IF NOT EXISTS capsules_feedback (
            id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Identifiant unique du feedback',
            listen_history_id INT NOT NULL COMMENT 'Référence à l''événement d''écoute',
            user_id INT NOT NULL COMMENT 'Identifiant de l''utilisateur',
            capsule_id INT NOT NULL COMMENT 'Identifiant de la capsule audio',
            rating INT NOT NULL COMMENT 'Note de satisfaction (1-5)',
            feedback_text TEXT COMMENT 'Commentaire textuel de l''utilisateur',
            audio_feedback_file VARCHAR(255) COMMENT 'Nom du fichier audio de feedback',
            audio_url TEXT COMMENT 'URL temporaire d''accès au feedback audio',
            feedback_type ENUM('text', 'audio', 'both') NOT NULL DEFAULT 'text' COMMENT 'Type de feedback',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Date de création',
            FOREIGN KEY (listen_history_id) REFERENCES capsules_history(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (capsule_id) REFERENCES capsules(capsule_id) ON DELETE CASCADE,
            INDEX idx_listen_history (listen_history_id),
            INDEX idx_user_capsule (user_id, capsule_id),
            INDEX idx_created_at (created_at)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        COMMENT = 'Feedbacks des utilisateurs sur les capsules audio';
            ''',
            '''
        -- Table pour les actions de réservation des utilisateurs
        CREATE TABLE IF NOT EXISTS user_booking_actions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            product_id VARCHAR(50) NOT NULL,
            booking_id VARCHAR(100) NOT NULL,
            action_type VARCHAR(20) NOT NULL,
            reason TEXT,
            old_datetime DATETIME,
            new_datetime DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_user_product (user_id, product_id),
            INDEX idx_booking (booking_id),
            INDEX idx_action (action_type),
            INDEX idx_created (created_at)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        COMMENT = 'Actions de réservation des utilisateurs (création, modification, annulation)';
            ''',
            '''
        CREATE TABLE IF NOT EXISTS user_actions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            action VARCHAR(100) NOT NULL,
            details JSON,
            ip_address VARCHAR(45),
            user_agent TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_user (user_id),
            INDEX idx_action (action),
            INDEX idx_created (created_at)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        COMMENT = 'Journal des actions utilisateurs pour audit et analytics';
            '''
            '''
        CREATE TABLE IF NOT EXISTS audio_transcriptions (
            id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Identifiant unique de la transcription',
            quiz_session_id INT NOT NULL COMMENT 'Session de quiz associée',
            question_id INT NOT NULL COMMENT 'Question associée',
            user_id INT NOT NULL COMMENT 'Utilisateur concerné',
            quiz_id VARCHAR(100) NOT NULL COMMENT 'Quiz associé',
            audio_file_path TEXT NOT NULL COMMENT 'Chemin du fichier audio (gs://...)',
            transcription TEXT NOT NULL COMMENT 'Texte transcrit',
            confidence_score DECIMAL(3,2) COMMENT 'Score de confiance de la transcription',
            transcription_status ENUM('pending', 'completed', 'error') NOT NULL DEFAULT 'completed' COMMENT 'Statut de la transcription',
            error_message TEXT COMMENT 'Message d erreur éventuel',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Date de création',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Date de mise à jour',
            FOREIGN KEY (quiz_session_id) REFERENCES quiz_user(quiz_session_id) ON DELETE CASCADE,
            FOREIGN KEY (question_id) REFERENCES questions_catalog(question_id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (quiz_id) REFERENCES quiz_catalog(quiz_id) ON DELETE CASCADE,
            INDEX idx_quiz_session (quiz_session_id),
            INDEX idx_question (question_id),
            INDEX idx_user (user_id),
            UNIQUE KEY unique_transcription (quiz_session_id, question_id)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        COMMENT = 'Transcriptions audio des réponses aux questions';
        ''',
        '''
        CREATE TABLE IF NOT EXISTS analysis_access_tokens (
            id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Identifiant unique',
            token VARCHAR(255) NOT NULL UNIQUE COMMENT 'Token d''accès unique',
            user_id INT NOT NULL COMMENT 'Utilisateur (lead ou user)',
            quiz_id VARCHAR(100) NOT NULL COMMENT 'Quiz associé',
            result_id VARCHAR(100) NULL COMMENT 'Résultat associé',
            
            -- Sécurité temporelle
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Date de création',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Date de dernière modification (tracking upgrade)',
            expires_at TIMESTAMP NULL COMMENT 'Expiration (NULL = illimité pour paid)',
            
            -- Quotas
            max_views INT NULL COMMENT 'Nombre max de consultations (NULL = illimité pour paid)',
            view_count INT DEFAULT 0 COMMENT 'Nombre de vues actuelles',
            last_viewed_at TIMESTAMP NULL COMMENT 'Date de dernière consultation',
            
            -- Révocation manuelle
            is_revoked BOOLEAN DEFAULT FALSE COMMENT 'Token révoqué manuellement',
            
            -- Type d'accès
            access_type ENUM('free', 'paid') DEFAULT 'free' COMMENT 'Type d''accès : free (limité) ou paid (illimité)',
            
            -- Index pour performances
            INDEX idx_token (token),
            INDEX idx_user (user_id),
            INDEX idx_expires (expires_at),
            INDEX idx_access_type (access_type),
            INDEX idx_quiz_result (quiz_id, result_id),
            
            -- Contraintes
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (quiz_id) REFERENCES quiz_catalog(quiz_id) ON DELETE CASCADE
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        COMMENT = 'Tokens d''accès temporaires pour analyses quiz - Free (7j, 3 vues) ou Paid (illimité)';
        '''
        ,
        '''
        CREATE TABLE IF NOT EXISTS user_consent_history (
            consent_history_id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Unique identifier for consent history record',
            user_id INT NOT NULL COMMENT 'Reference to user who changed consent',
            consent_type ENUM('newsletter', 'partner') NOT NULL COMMENT 'Type of consent (newsletter or partner)',
            consent_status BOOLEAN NOT NULL COMMENT 'Consent status (TRUE=opt-in, FALSE=opt-out)',
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Timestamp when consent was changed',
            ip_address VARCHAR(45) NULL COMMENT 'IP address of user when consent changed (RGPD compliance)',
            source ENUM(
                'account_page',
                'registration',
                'email_unsubscribe',
                'email_preference_center',
                'admin_manual',
                'api_sync',
                'gdpr_request',
                'import',
                'webhook_brevo'
            ) NOT NULL DEFAULT 'account_page' COMMENT 'Source of consent change',
            
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            INDEX idx_user_consent (user_id, consent_type, changed_at),
            INDEX idx_source (source, changed_at),
            INDEX idx_consent_status (consent_status, changed_at)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        COMMENT = 'Historique des consentements utilisateur pour conformité RGPD et traçabilité';
        ''',
        '''
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NULL,
            email VARCHAR(255) NOT NULL,
            message TEXT NOT NULL,
            context JSON NULL,
            created_at DATETIME NOT NULL,
            status ENUM('pending', 'replied', 'archived') DEFAULT 'pending',
            replied_at DATETIME NULL,
            replied_by INT NULL,
            notes TEXT NULL,
            INDEX idx_email (email),
            INDEX idx_user_id (user_id),
            INDEX idx_status (status),
            INDEX idx_created_at (created_at),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL,
            FOREIGN KEY (replied_by) REFERENCES users(user_id) ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        ''',
        '''
        CREATE TABLE IF NOT EXISTS analysis_validation_logs (
            id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'ID unique de log',
            result_id VARCHAR(100) NOT NULL COMMENT 'Analyse concernée',
            step_id VARCHAR(100) NOT NULL COMMENT 'Étape (career_path, etc.)',
            user_id INT NOT NULL COMMENT 'Utilisateur concerné',
            attempt_number INT NOT NULL COMMENT 'Numéro de tentative (1, 2, 3...)',
            validation_status ENUM('success', 'failed', 'skipped') NOT NULL COMMENT 'Résultat de cette tentative',
            issues_detected JSON NULL COMMENT 'Liste structurée des problèmes détectés par le validator',
            issues_count INT DEFAULT 0 COMMENT 'Nombre total de problèmes',
            critical_issues_count INT DEFAULT 0 COMMENT 'Nombre de problèmes critiques',
            resolution_type ENUM('auto_fixed', 'manual_review', 'accepted_as_is') NULL COMMENT 'Comment le problème a été résolu',
            validation_duration_seconds DECIMAL(6,2) NULL COMMENT 'Durée de cette tentative de validation',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Date de la tentative',
            INDEX idx_result (result_id, step_id),
            INDEX idx_user (user_id),
            INDEX idx_status (validation_status),
            INDEX idx_created (created_at),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        COMMENT = 'Historique DÉTAILLÉ de chaque validation d''analyse - Permet monitoring et amélioration continue';
        ''',
        '''
        CREATE TABLE IF NOT EXISTS analysis_queue (
            id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Identifiant unique de la tâche',
            user_id INT NOT NULL COMMENT 'Utilisateur concerné',
            quiz_id VARCHAR(100) NOT NULL COMMENT 'Quiz concerné',
            order_id INT NULL COMMENT 'Commande associée (pour tracking)',
            
            -- Statuts
            analysis_status ENUM('pending', 'processing', 'completed', 'failed') 
                NOT NULL DEFAULT 'pending' COMMENT 'État de la génération',
            
            -- Timestamps
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Date de création',
            started_at TIMESTAMP NULL COMMENT 'Date de début de traitement',
            completed_at TIMESTAMP NULL COMMENT 'Date de fin',
            
            -- Retry & Error handling
            retry_count INT DEFAULT 0 COMMENT 'Nombre de tentatives',
            error_message TEXT NULL COMMENT 'Message d erreur si échec',
            
            -- Résultat
            result_id VARCHAR(100) NULL COMMENT 'ID du résultat généré',
            
            -- Index pour performances
            INDEX idx_user_quiz (user_id, quiz_id),
            INDEX idx_status (analysis_status),
            INDEX idx_created (created_at),
            
            -- Contraintes
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (quiz_id) REFERENCES quiz_catalog(quiz_id) ON DELETE CASCADE,
            FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE SET NULL
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        COMMENT = 'Queue de génération des analyses - Permet le traitement asynchrone';
        ''',
        '''
        CREATE TABLE IF NOT EXISTS analysis_notification_emails (
            id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Unique identifier',
            result_id VARCHAR(255) NOT NULL COMMENT 'Analysis result identifier',
            step_id VARCHAR(100) NOT NULL COMMENT 'Analysis step identifier',
            user_id INT NOT NULL COMMENT 'User who received the notification',
            quiz_id VARCHAR(100) NOT NULL COMMENT 'Associated quiz identifier',
            sent_to_email VARCHAR(255) NOT NULL COMMENT 'Email address used for sending',
            sent_by_admin_id INT NULL COMMENT 'Admin who sent the notification (NULL if admin deleted)',
            sent_at DATETIME NOT NULL COMMENT 'Timestamp when email was sent',
            INDEX idx_result_step (result_id, step_id),
            INDEX idx_user (user_id),
            INDEX idx_admin (sent_by_admin_id),
            INDEX idx_sent_at (sent_at),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (sent_by_admin_id) REFERENCES users(user_id) ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        COMMENT = 'History of analysis notification emails sent to users';
        ''',
        '''
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NULL,
            session_id VARCHAR(128),
            event_type VARCHAR(50) NOT NULL DEFAULT 'page_view',
            page_path VARCHAR(255),
            referrer VARCHAR(500),
            device_type VARCHAR(20),
            extra_data JSON NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_user_id (user_id),
            INDEX idx_session_id (session_id),
            INDEX idx_event_type (event_type),
            INDEX idx_page_path (page_path),
            INDEX idx_created_at (created_at),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        ''',
        '''
        CREATE TABLE IF NOT EXISTS user_help_requests (
            id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Identifiant unique de la demande',
            
            -- Identifiants utilisateur et contexte
            user_id INT NOT NULL COMMENT 'Utilisateur qui fait la demande',
            quiz_id VARCHAR(100) NOT NULL COMMENT 'Quiz associé à la demande',
            result_id VARCHAR(100) NULL COMMENT 'Analyse associée (si applicable)',
            
            -- Contexte de la piste/voie sélectionnée
            piste_number INT NULL COMMENT 'Numéro de la piste concernée (1, 2 ou 3)',
            piste_title VARCHAR(255) NULL COMMENT 'Titre de la piste (ex: Consultant RSE)',
            
            -- Type de demande
            request_type ENUM(
                'action_followup',      -- Suivi des actions recommandées
                'recruiter_connection', -- Mise en relation avec recruteurs
                'analysis_refinement',  -- Affiner/approfondir l'analyse
                'coach_session',        -- Session avec un coach
                'cv_review',            -- Relecture CV orientée reconversion
                'interview_prep',       -- Préparation entretien
                'training_info',        -- Infos sur formations
                'networking_help',      -- Aide au networking
                'other'                 -- Autre demande
            ) NOT NULL COMMENT 'Type de demande d accompagnement',
            
            -- Détails de la demande
            request_details TEXT NULL COMMENT 'Détails additionnels fournis par l utilisateur',
            
            -- Statut de traitement
            status ENUM(
                'pending',      -- En attente de traitement
                'contacted',    -- Utilisateur contacté
                'in_progress',  -- En cours de traitement
                'completed',    -- Demande traitée/terminée
                'cancelled'     -- Annulée
            ) NOT NULL DEFAULT 'pending' COMMENT 'Statut de la demande',
            
            -- Suivi admin
            assigned_to INT NULL COMMENT 'Admin/coach assigné à la demande',
            admin_notes TEXT NULL COMMENT 'Notes internes (non visibles par l utilisateur)',
            
            -- Priorité et urgence
            priority ENUM('low', 'normal', 'high', 'urgent') NOT NULL DEFAULT 'normal' COMMENT 'Priorité de traitement',
            
            -- Source de la demande
            source_page VARCHAR(100) NULL COMMENT 'Page d origine (analysis_view, dashboard, etc.)',
            source_action VARCHAR(100) NULL COMMENT 'Action déclencheuse (cta_click, modal_submit, etc.)',
            
            -- Timestamps
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Date de création',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Dernière mise à jour',
            contacted_at DATETIME NULL COMMENT 'Date du premier contact',
            completed_at DATETIME NULL COMMENT 'Date de clôture',
            
            -- Contraintes
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (quiz_id) REFERENCES quiz_catalog(quiz_id) ON DELETE CASCADE,
            FOREIGN KEY (assigned_to) REFERENCES users(user_id) ON DELETE SET NULL,
            
            -- Index pour performances
            INDEX idx_user_id (user_id),
            INDEX idx_status (status),
            INDEX idx_request_type (request_type),
            INDEX idx_priority (priority),
            INDEX idx_created_at (created_at),
            INDEX idx_assigned_to (assigned_to),
            INDEX idx_user_status (user_id, status)
            
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        COMMENT = 'Demandes d accompagnement et de suivi des utilisateurs';
        ''',
        '''
        CREATE TABLE IF NOT EXISTS user_unlocked_pistes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            quiz_id VARCHAR(100) NOT NULL,
            piste_number INT NOT NULL,
            token_code VARCHAR(255) NULL,
            unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (token_code) REFERENCES tokens(token_code) ON DELETE SET NULL,
            
            UNIQUE KEY unique_user_quiz_piste (user_id, quiz_id, piste_number),
            INDEX idx_user_quiz (user_id, quiz_id)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        ''',
        '''
        CREATE TABLE IF NOT EXISTS user_analysis_interactions (
            id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Identifiant unique',
            user_id INT NOT NULL COMMENT 'Utilisateur concerné',
            quiz_id VARCHAR(100) NOT NULL COMMENT 'Quiz associé',
            result_id VARCHAR(100) NULL COMMENT 'Analyse associée',
            piste_number INT NULL COMMENT 'Piste concernée (1, 2, 3 ou NULL si global)',
            
            interaction_type ENUM(
                'accuracy_feedback',
                'piste_feedback',
                'pack_interest',
                'booking_request',
                'section_view'
            ) NOT NULL COMMENT 'Type d interaction',
            
            payload JSON NOT NULL COMMENT 'Données spécifiques au type d interaction',
            
            source_page VARCHAR(100) NULL COMMENT 'Page d origine',
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Date de création',
            
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (quiz_id) REFERENCES quiz_catalog(quiz_id) ON DELETE CASCADE,
            
            INDEX idx_user (user_id),
            INDEX idx_quiz (quiz_id),
            INDEX idx_type (interaction_type),
            INDEX idx_user_quiz_type (user_id, quiz_id, interaction_type),
            INDEX idx_created (created_at)
        ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        COMMENT = 'Interactions utilisateur sur les analyses (feedbacks, intérêts packs, RDV)';
        ''',
        '''
        CREATE TABLE IF NOT EXISTS cron_slack_log (
            id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Unique identifier',
            cron_name VARCHAR(100) NOT NULL COMMENT 'Name of the cron job',
            sent_at DATETIME NOT NULL COMMENT 'Timestamp when Slack notification was sent',
            INDEX idx_cron_date (cron_name, sent_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        COMMENT = 'Tracks Slack notifications sent by cron jobs to avoid duplicates';
        ''',
        '''
        -- Table pour les leads Tilto Pro (formulaire landing page)
        CREATE TABLE IF NOT EXISTS pro_leads (
            id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'Identifiant unique',
            firstname VARCHAR(100) NOT NULL COMMENT 'Prénom',
            lastname VARCHAR(100) NOT NULL COMMENT 'Nom',
            email VARCHAR(255) NOT NULL COMMENT 'Email professionnel',
            activite VARCHAR(100) NULL COMMENT 'Type d activité (coach_independant, bilan, cep, cabinet, autre)',
            source VARCHAR(100) DEFAULT 'tilto_pro_landing' COMMENT 'Source du lead',
            status ENUM('new', 'contacted', 'demo_planned', 'demo_done', 'converted', 'lost') DEFAULT 'new' COMMENT 'Statut du lead',
            notes TEXT NULL COMMENT 'Notes internes',
            ip_address VARCHAR(45) NULL COMMENT 'IP du visiteur',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Date de soumission',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Dernière mise à jour',
            INDEX idx_email (email),
            INDEX idx_status (status),
            INDEX idx_created (created_at),
            INDEX idx_activite (activite)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        COMMENT = 'Leads B2B collectés via la landing page Tilto Pro';
        '''
        ]
 
        try:
            for query in queries:
                try:
                    with mysql.connection.cursor() as cursor:
                        cursor.execute(query)
                        # Appelle .fetchall() même si tu ne t'en sers pas, pour vider les résultats résiduels
                        while cursor.nextset():
                            pass
                        mysql.connection.commit()
                        logger.info("Executed query successfully.")
                except Exception as e:
                    if "already exists" in str(e).lower() and force_init:
                        logger.warning(f"Table already exists, continuing: {e}")
                        continue
                    logger.error(f"Error executing query: {e}")
                    try:
                        mysql.connection.rollback()
                    except Exception as rollback_error:
                        logger.warning(f"Rollback failed: {rollback_error}")
                    raise
        except Exception as e:
            logger.error(f"Error during database initialization: {e}")
            raise


        logger.info("Database initialization and optimization complete")

    finally:
        if cursor:
            try:
                cursor.close()
            except Exception as close_error:
                logger.warning(f"Failed to close initial cursor: {close_error}")


