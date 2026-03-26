"""
Database management module for quiz and product catalog system.
This module provides a comprehensive set of tools for managing the database,
including user management, quiz catalogs, product catalogs, and various utility functions.

Main components:
- User management (User model)
- Database initialization and updates
- Quiz and question management
- Product catalog management
- Data loading and processing utilities
- Audio capsules management

Usage:
 from models import User, init_db, update_database
 # Initialize database
 init_db()
 # Update from CSV files
 update_database()
"""
import logging
from typing import List, Dict, Any, Optional, Tuple

# Import models
from .user_model import User
from .audio_capsule import AudioCapsuleModel, UserCapsuleModel

# Database initialization and schema management
from .db_init import init_db

# Core database loading and update functions
from .db_loader import (
    # Main update function
    update_database,
    # Quiz management
    load_quiz_catalog,
    load_quiz_questions,
    update_quiz_catalog,
    update_quiz_questions,
    # Question management
    load_questions,
    update_questions,
    # Product management
    load_product_catalog,
    load_product_catalog_items,
    load_product_items,
    update_products,
    # Relationship management
    load_item_quiz,
    update_item_quiz,
    # Utility functions
    get_csv_path,
    clean_quotes,
    parse_bool,
    safe_int,
    safe_float,
    load_csv_file
)

# Type definitions for better code completion and type checking
QuizData = Dict[str, Any]
ProductData = Dict[str, Any]
ItemData = Dict[str, Any]
QuestionData = Dict[str, Any]
ChoiceData = Dict[str, Any]
AudioCapsuleData = Dict[str, Any]

# Define public API
__all__ = [
    # Core models
    'User',
    'AudioCapsuleModel',
    'UserCapsuleModel',
    # Database initialization
    'init_db',
    'update_database',
    # Quiz and question management
    'load_quiz_catalog',
    'load_quiz_questions',
    'load_questions',
    'update_quiz_catalog',
    'update_quiz_questions',
    'update_questions',
    # Product management
    'load_product_catalog',
    'load_product_catalog_items',
    'load_product_items',
    'update_products',
    # Relationship management
    'load_item_quiz',
    'update_item_quiz',
    # Utility functions
    'get_csv_path',
    'clean_quotes',
    'parse_bool',
    'safe_int',
    'safe_float',
    'load_csv_file',
    # Type definitions
    'QuizData',
    'ProductData',
    'ItemData',
    'QuestionData',
    'ChoiceData',
    'AudioCapsuleData'
]

# Configure logging
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# Version information
__version__ = '1.0.0'
__author__ = 'Your Company'
__license__ = 'Proprietary'

# Module initialization
def initialize_module() -> None:
    """Initialize the module with default configuration."""
    logger.debug("Initializing database module")
    
    # Set default logging format for module
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Add console handler if none exists
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    logger.debug("Database module initialized successfully")

# Initialize module when imported
initialize_module()