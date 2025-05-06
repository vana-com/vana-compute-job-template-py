from pathlib import Path
import sqlite3
import json
import sys
from typing import Dict, Any
from query_engine_client import QueryEngineClient
from container_params import ContainerParams, ContainerParamError

def get_user_locales(db_path: Path) -> Dict[str, float]:
    """Query the SQLite database and extract user_id: locale mapping.
    
    Args:
        db_path: Path to the SQLite database file
        
    Returns:
        Dictionary with user_id as keys and locale as values
        
    Raises:
        Exception: If there's an error connecting to or querying the database
    """
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Query user_id and locale from the results table
        cursor.execute('SELECT user_id, locale FROM results')
        
        # Create a dictionary with user_id as keys and locale as values
        user_locales = {}
        for row in cursor.fetchall():
            user_id, locale = row
            user_locales[str(user_id)] = locale
        
        conn.close()
        return user_locales
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        raise
    except Exception as e:
        print(f"Error querying database: {e}")
        raise

def save_stats_to_json(data: Dict[str, Any], output_path: Path) -> None:
    """Save data to a JSON file.
    
    Args:
        data: Data to save (dictionary that can be JSON serialized)
        output_path: Path where the JSON file will be saved
        
    Raises:
        Exception: If there's an error creating the output directory or saving the file
    """
    try:
        # Ensure the output directory exists
        output_dir = output_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Save to JSON
        with open(output_path, "w") as f:
            json.dump(data, f, indent=4)
            
        print(f"Stats saved to {output_path}")
    except Exception as e:
        print(f"Error saving JSON: {e}")
        raise

def execute_query(params: ContainerParams) -> bool:
    """Execute the query using the query engine client.
    
    Args:
        params: Container parameters with query details
        
    Returns:
        True if query execution was successful, False otherwise
    """
    if not params.validate_production_mode():
        return False
        
    # Initialize query engine client
    query_engine_client = QueryEngineClient(
        params.query, 
        params.query_signature, 
        str(params.db_path)
    )
    
    # Execute query
    print(f"Executing query: {params.query}")
    query_result = query_engine_client.execute_query(
        params.compute_job_id, 
        params.data_refiner_id,
        params.query_params
    )
    
    if not query_result.success:
        print(f"Error executing query: {query_result.error}")
        return False
        
    print(f"Query executed successfully, processing results from {params.db_path}")
    return True

def process_results(params: ContainerParams) -> None:
    """Process query results and generate stats file.
    
    Args:
        params: Container parameters
    """
    user_data = get_user_locales(params.db_path)
    
    if user_data:
        print(f"Found {len(user_data)} users in the database")
        save_stats_to_json(user_data, params.stats_path)
    else:
        print("No user stats found in the database")
        # Create an empty stats file to indicate processing completed
        save_stats_to_json({}, params.stats_path)

def main() -> None:
    """Main entry point for the worker."""
    try:
        # Load parameters from environment variables
        try:
            params = ContainerParams.from_env()
        except ContainerParamError as e:
            print(f"Error in container parameters: {e}")
            sys.exit(1)
        
        # Handle development vs production mode
        if params.dev_mode:
            print("Running in DEVELOPMENT MODE - using local database file")
            print(f"Processing query results from {params.db_path}")
        else:
            # In production mode, execute the query first
            if not execute_query(params):
                sys.exit(2)
        
        # Process results (whether from dev mode or query execution)
        process_results(params)
        
    except Exception as e:
        print(f"Error in worker execution: {e}")
        sys.exit(3)

if __name__ == "__main__":
    main()