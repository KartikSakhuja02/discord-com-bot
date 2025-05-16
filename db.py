"""
Database module for the Discord Tournament Bot

This module handles all database-related functionality:
1. Connection management
2. Schema creation and maintenance
3. Player data (points, stats)
4. Match history
5. Leaderboard functionality

Configuration is stored in DB_CONFIG dictionary.
"""

import mysql.connector
from mysql.connector import Error
import logging
import asyncio
from collections import Counter
import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("db.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("db")

# Database connection configuration
# Set these environment variables for secure configuration:
# - DB_HOST: MySQL server hostname (default: localhost)
# - DB_USER: MySQL username (default: root)
# - DB_PASSWORD: MySQL password (default: password)
# - DB_DATABASE: MySQL database name (default: discord_tournament)
DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'user': os.environ.get('DB_USER', 'root'),
    'password': os.environ.get('DB_PASSWORD', 'password'),
    'database': os.environ.get('DB_DATABASE', 'discord_tournament')
}

# ==========================================
# Connection Management
# ==========================================

def create_connection():
    """Create a connection to the MySQL database"""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        logger.error(f"Error connecting to MySQL database: {e}")
        logger.info("Make sure you've set the correct database environment variables (DB_HOST, DB_USER, DB_PASSWORD, DB_DATABASE)")
        return None

def execute_query(query, params=None, fetch=False, many=False):
    """Execute a query with proper error handling"""
    try:
        conn = create_connection()
        if not conn:
            logger.error("Failed to create database connection")
            return None

        cursor = conn.cursor(dictionary=True) if fetch else conn.cursor()
        
        if many and params:
            cursor.executemany(query, params)
        elif params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
            
        if fetch:
            result = cursor.fetchall()
        else:
            conn.commit()
            result = cursor.lastrowid
            
        cursor.close()
        conn.close()
        return result
    except Error as e:
        logger.error(f"Database error: {e}")
        if 'conn' in locals() and conn.is_connected():
            conn.close()
        return None

# ==========================================
# Database Initialization
# ==========================================

async def initialize_database():
    """Create database and tables if they don't exist"""
    try:
        # Create database if it doesn't exist
        conn = mysql.connector.connect(
            host=DB_CONFIG['host'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password']
        )
        
        if conn:
            cursor = conn.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['database']}")
            cursor.close()
            conn.close()
            
            # Connect to the created database
            conn = create_connection()
            if conn:
                cursor = conn.cursor()
                
                # Create players table
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS players (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    discord_id VARCHAR(32) UNIQUE,
                    username VARCHAR(100),
                    points INT DEFAULT 0,
                    matches_played INT DEFAULT 0,
                    wins INT DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
                """)
                
                # Create matches table
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS matches (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    queue_number INT,
                    team1_captain VARCHAR(32),
                    team2_captain VARCHAR(32),
                    winner_team INT,
                    map_played VARCHAR(50),
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)
                
                # Create match_players table
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS match_players (
                    match_id INT,
                    player_id VARCHAR(32),
                    team_number INT,
                    FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
                    PRIMARY KEY (match_id, player_id)
                )
                """)
                
                conn.commit()
                cursor.close()
                conn.close()
                logger.info("Database initialized successfully")
                return True
    except Error as e:
        logger.error(f"Error initializing database: {e}")
    return False

# ==========================================
# Player Management Functions
# ==========================================

async def get_player_points(discord_id):
    """Get a player's points from the database"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT points FROM players WHERE discord_id = %s", (str(discord_id),))
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if result:
                return result['points']
            else:
                # Player not found, create player entry
                await create_player(discord_id, 0)
                return 0
    except Error as e:
        logger.error(f"Error getting player points: {e}")
    return 0

async def create_player(discord_id, points=0, username=None):
    """Create a new player in the database"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor()
            if username:
                cursor.execute(
                    "INSERT IGNORE INTO players (discord_id, points, username) VALUES (%s, %s, %s)",
                    (str(discord_id), points, username)
                )
            else:
                cursor.execute(
                    "INSERT IGNORE INTO players (discord_id, points) VALUES (%s, %s)",
                    (str(discord_id), points)
                )
            conn.commit()
            cursor.close()
            conn.close()
            return True
    except Error as e:
        logger.error(f"Error creating player: {e}")
    return False

async def update_player_points(discord_id, points_to_add, win=False, username=None):
    """Update a player's points in the database"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor()
            if username:
                cursor.execute(
                    "INSERT INTO players (discord_id, points, matches_played, wins, username) VALUES (%s, %s, 1, %s, %s) "
                    "ON DUPLICATE KEY UPDATE points = points + %s, matches_played = matches_played + 1, wins = wins + %s, username = %s",
                    (str(discord_id), points_to_add, 1 if win else 0, username, points_to_add, 1 if win else 0, username)
                )
            else:
                cursor.execute(
                    "INSERT INTO players (discord_id, points, matches_played, wins) VALUES (%s, %s, 1, %s) "
                    "ON DUPLICATE KEY UPDATE points = points + %s, matches_played = matches_played + 1, wins = wins + %s",
                    (str(discord_id), points_to_add, 1 if win else 0, points_to_add, 1 if win else 0)
                )
            conn.commit()
            cursor.close()
            conn.close()
            return True
    except Error as e:
        logger.error(f"Error updating player points: {e}")
    return False

async def get_player_stats(discord_id):
    """Get a player's complete stats"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM players WHERE discord_id = %s", (str(discord_id),))
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if result:
                return result
            else:
                await create_player(discord_id)
                return {
                    'discord_id': str(discord_id),
                    'points': 0,
                    'matches_played': 0,
                    'wins': 0
                }
    except Error as e:
        logger.error(f"Error getting player stats: {e}")
    return None

async def get_player_match_history(discord_id, limit=5):
    """Get a player's match history"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT m.*, mp.team_number 
                FROM matches m 
                JOIN match_players mp ON m.id = mp.match_id 
                WHERE mp.player_id = %s 
                ORDER BY m.timestamp DESC 
                LIMIT %s
            """, (str(discord_id), limit))
            
            matches = cursor.fetchall()
            cursor.close()
            conn.close()
            return matches
    except Error as e:
        logger.error(f"Error getting player match history: {e}")
    return []

# ==========================================
# Match Management Functions
# ==========================================

async def create_match(queue_num, team1_captain, team2_captain, map_played):
    """Create a new match in the database"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO matches (queue_number, team1_captain, team2_captain, map_played) "
                "VALUES (%s, %s, %s, %s)",
                (queue_num, str(team1_captain.id), str(team2_captain.id), map_played)
            )
            conn.commit()
            match_id = cursor.lastrowid
            cursor.close()
            conn.close()
            logger.info(f"Created match {match_id} for queue {queue_num}")
            return match_id
    except Error as e:
        logger.error(f"Error creating match: {e}")
    return None

async def register_players_in_match(match_id, team1, team2):
    """Register all players in a match"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor()
            
            # Register team 1 players
            for player in team1:
                cursor.execute(
                    "INSERT INTO match_players (match_id, player_id, team_number) VALUES (%s, %s, 1)",
                    (match_id, str(player.id))
                )
                # Create player if not exists
                await create_player(str(player.id), username=player.display_name)
                
            # Register team 2 players
            for player in team2:
                cursor.execute(
                    "INSERT INTO match_players (match_id, player_id, team_number) VALUES (%s, %s, 2)",
                    (match_id, str(player.id))
                )
                # Create player if not exists
                await create_player(str(player.id), username=player.display_name)
                
            conn.commit()
            cursor.close()
            conn.close()
            return True
    except Error as e:
        logger.error(f"Error registering players in match: {e}")
    return False

async def update_match_winner(match_id, winning_team):
    """Update the match with the winning team"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE matches SET winner_team = %s WHERE id = %s",
                (winning_team, match_id)
            )
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"Updated match {match_id} with winner: Team {winning_team}")
            return True
    except Error as e:
        logger.error(f"Error updating match winner: {e}")
    return False

async def get_match_details(match_id):
    """Get complete details about a match"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            
            # Get match data
            cursor.execute("SELECT * FROM matches WHERE id = %s", (match_id,))
            match = cursor.fetchone()
            
            if not match:
                cursor.close()
                conn.close()
                return None
                
            # Get players for team 1
            cursor.execute("""
                SELECT p.* FROM players p
                JOIN match_players mp ON p.discord_id = mp.player_id
                WHERE mp.match_id = %s AND mp.team_number = 1
            """, (match_id,))
            team1_players = cursor.fetchall()
            
            # Get players for team 2
            cursor.execute("""
                SELECT p.* FROM players p
                JOIN match_players mp ON p.discord_id = mp.player_id
                WHERE mp.match_id = %s AND mp.team_number = 2
            """, (match_id,))
            team2_players = cursor.fetchall()
            
            cursor.close()
            conn.close()
            
            return {
                'match': match,
                'team1': team1_players,
                'team2': team2_players
            }
    except Error as e:
        logger.error(f"Error getting match details: {e}")
    return None

# ==========================================
# Stats and Leaderboard Functions
# ==========================================

async def get_leaderboard(limit=10):
    """Get the top players by points"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT * FROM players ORDER BY points DESC LIMIT %s",
                (limit,)
            )
            top_players = cursor.fetchall()
            cursor.close()
            conn.close()
            return top_players
    except Error as e:
        logger.error(f"Error getting leaderboard: {e}")
    return []

async def get_match_history(queue_num=None, limit=5):
    """Get match history, optionally filtered by queue"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            
            if queue_num is not None:
                cursor.execute(
                    "SELECT * FROM matches WHERE queue_number = %s ORDER BY timestamp DESC LIMIT %s",
                    (queue_num, limit)
                )
            else:
                cursor.execute(
                    "SELECT * FROM matches ORDER BY timestamp DESC LIMIT %s",
                    (limit,)
                )
                
            matches = cursor.fetchall()
            cursor.close()
            conn.close()
            return matches
    except Error as e:
        logger.error(f"Error getting match history: {e}")
    return []

async def get_queue_stats(queue_num, limit=5):
    """Get statistics for a specific queue"""
    try:
        recent_matches = await get_match_history(queue_num, limit)
        
        if not recent_matches:
            return None
            
        # Count wins per team
        team1_wins = sum(1 for match in recent_matches if match['winner_team'] == 1)
        team2_wins = sum(1 for match in recent_matches if match['winner_team'] == 2)
        
        # Calculate most played maps
        map_counts = Counter([match['map_played'] for match in recent_matches if match['map_played'

"""
Database module for Discord Tournament Bot

This module handles all database interactions including:
- Database initialization
- Player stats tracking
- Match history
- Leaderboard functionality

Configuration is stored in DB_CONFIG and can be modified as needed.
"""

import mysql.connector
from mysql.connector import Error
import logging
import asyncio
from collections import Counter
import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("db.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("db")

# Database connection configuration
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'password',
    'database': 'discord_tournament'
}

# Database connection and initialization functions
def create_connection():
    """Create a connection to the MySQL database"""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        logger.error(f"Error connecting to MySQL database: {e}")
        return None

async def initialize_database():
    """Create database and tables if they don't exist"""
    try:
        # Create database if it doesn't exist
        conn = mysql.connector.connect(
            host=DB_CONFIG['host'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password']
        )
        
        if conn:
            cursor = conn.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['database']}")
            cursor.close()
            conn.close()
            
            # Connect to the created database
            conn = create_connection()
            if conn:
                cursor = conn.cursor()
                
                # Create players table
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS players (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    discord_id VARCHAR(32) UNIQUE,
                    username VARCHAR(100),
                    points INT DEFAULT 0,
                    matches_played INT DEFAULT 0,
                    wins INT DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
                """)
                
                # Create matches table
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS matches (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    queue_number INT,
                    team1_captain VARCHAR(32),
                    team2_captain VARCHAR(32),
                    winner_team INT,
                    map_played VARCHAR(50),
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)
                
                # Create match_players table
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS match_players (
                    match_id INT,
                    player_id VARCHAR(32),
                    team_number INT,
                    FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
                    PRIMARY KEY (match_id, player_id)
                )
                """)
                
                conn.commit()
                cursor.close()
                conn.close()
                logger.info("Database initialized successfully")
                return True
    except Error as e:
        logger.error(f"Error initializing database: {e}")
    return False

# Player data functions
async def get_player_points(discord_id):
    """Get a player's points from the database"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT points FROM players WHERE discord_id = %s", (str(discord_id),))
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if result:
                return result['points']
            else:
                # Player not found, create player entry
                await create_player(discord_id, 0)
                return 0
    except Error as e:
        logger.error(f"Error getting player points: {e}")
    return 0

async def create_player(discord_id, points=0, username=None):
    """Create a new player in the database"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor()
            if username:
                cursor.execute(
                    "INSERT IGNORE INTO players (discord_id, points, username) VALUES (%s, %s, %s)",
                    (str(discord_id), points, username)
                )
            else:
                cursor.execute(
                    "INSERT IGNORE INTO players (discord_id, points) VALUES (%s, %s)",
                    (str(discord_id), points)
                )
            conn.commit()
            cursor.close()
            conn.close()
            return True
    except Error as e:
        logger.error(f"Error creating player: {e}")
    return False

async def update_player_points(discord_id, points_to_add, win=False, username=None):
    """Update a player's points in the database"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor()
            if username:
                cursor.execute(
                    "INSERT INTO players (discord_id, points, matches_played, wins, username) VALUES (%s, %s, 1, %s, %s) "
                    "ON DUPLICATE KEY UPDATE points = points + %s, matches_played = matches_played + 1, wins = wins + %s, username = %s",
                    (str(discord_id), points_to_add, 1 if win else 0, username, points_to_add, 1 if win else 0, username)
                )
            else:
                cursor.execute(
                    "INSERT INTO players (discord_id, points, matches_played, wins) VALUES (%s, %s, 1, %s) "
                    "ON DUPLICATE KEY UPDATE points = points + %s, matches_played = matches_played + 1, wins = wins + %s",
                    (str(discord_id), points_to_add, 1 if win else 0, points_to_add, 1 if win else 0)
                )
            conn.commit()
            cursor.close()
            conn.close()
            return True
    except Error as e:
        logger.error(f"Error updating player points: {e}")
    return False

async def get_player_stats(discord_id):
    """Get a player's complete stats"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM players WHERE discord_id = %s", (str(discord_id),))
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if result:
                return result
            else:
                await create_player(discord_id)
                return {
                    'discord_id': str(discord_id),
                    'points': 0,
                    'matches_played': 0,
                    'wins': 0
                }
    except Error as e:
        logger.error(f"Error getting player stats: {e}")
    return None

# Match tracking functions
async def create_match(queue_num, team1_captain, team2_captain, map_played):
    """Create a new match in the database"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO matches (queue_number, team1_captain, team2_captain, map_played) "
                "VALUES (%s, %s, %s, %s)",
                (queue_num, str(team1_captain.id), str(team2_captain.id), map_played)
            )
            conn.commit()
            match_id = cursor.lastrowid
            cursor.close()
            conn.close()
            return match_id
    except Error as e:
        logger.error(f"Error creating match: {e}")
    return None

async def register_players_in_match(match_id, team1, team2):
    """Register all players in a match"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor()
            
            # Register team 1 players
            for player in team1:
                cursor.execute(
                    "INSERT INTO match_players (match_id, player_id, team_number) VALUES (%s, %s, 1)",
                    (match_id, str(player.id))
                )
                # Create player if not exists
                await create_player(str(player.id), username=player.display_name)
                
            # Register team 2 players
            for player in team2:
                cursor.execute(
                    "INSERT INTO match_players (match_id, player_id, team_number) VALUES (%s, %s, 2)",
                    (match_id, str(player.id))
                )
                # Create player if not exists
                await create_player(str(player.id), username=player.display_name)
                
            conn.commit()
            cursor.close()
            conn.close()
            return True
    except Error as e:
        logger.error(f"Error registering players in match: {e}")
    return False

async def update_match_winner(match_id, winning_team):
    """Update the match with the winning team"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE matches SET winner_team = %s WHERE id = %s",
                (winning_team, match_id)
            )
            conn.commit()
            cursor.close()
            conn.close()
            return True
    except Error as e:
        logger.error(f"Error updating match winner: {e}")
    return False

async def get_leaderboard(limit=10):
    """Get the top players by points"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT * FROM players ORDER BY points DESC LIMIT %s",
                (limit,)
            )
            top_players = cursor.fetchall()
            cursor.close()
            conn.close()
            return top_players
    except Error as e:
        logger.error(f"Error getting leaderboard: {e}")
    return []

async def get_queue_stats(queue_num, limit=5):
    """Get statistics for a specific queue"""
    try:
        conn = create_connection()
        if conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT * FROM matches WHERE queue_number = %s ORDER BY timestamp DESC LIMIT %s",
                (queue_num, limit)
            )
            recent_matches = cursor.fetchall()
            cursor.close()
            conn.close()
            
            if not recent_matches:
                return None
                
            # Count wins per team
            team1_wins = sum(1 for match in recent_matches if match['winner_team'] == 1)
            team2_wins = sum(1 for match in recent_matches if match['winner_team'] == 2)
            
            # Calculate most played maps
            map_counts = Counter([match['map_played'] for match in recent_matches if match['map_played']])
            most_common_maps = map_counts.most_common(3)
            
            return {
                'recent_matches': recent_matches,
                'team1_wins': team1_wins,
                'team2_wins': team2_wins,
                'most_common_maps': most_common_maps
            }
    except Error as e:
        logger.error(f"Error getting queue stats: {e}")
    return None

# Test connection when module is imported
def test_connection():
    conn = create_connection()
    if conn:
        logger.info("Database connection successful")
        conn.close()
        return True
    else:
        logger.error("Database connection failed")
        return False

if __name__ == "__main__":
    # Test database connection if run directly
    test_connection()
    print("Database module initialized. Run this within the bot for full functionality.")

