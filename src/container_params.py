from dataclasses import dataclass
from pathlib import Path
import os
import json
from typing import Optional, List, Any

class ContainerParamError(Exception):
    """Base class for container parameter errors."""
    pass

@dataclass
class ContainerParams:
    """Container parameters for data exchange between host and job container."""
    input_path: Path
    output_path: Path
    dev_mode: bool
    
    # Required in production mode
    query: Optional[str] = None
    query_signature: Optional[str] = None
    query_params: Optional[List[Any]] = None
    compute_job_id: Optional[int] = None
    data_refiner_id: Optional[int] = None
    
    @classmethod
    def from_env(cls) -> 'ContainerParams':
        """Create ContainerParams from environment variables."""
        input_path = Path(os.getenv("INPUT_PATH", "/mnt/input"))
        output_path = Path(os.getenv("OUTPUT_PATH", "/mnt/output"))
        dev_mode = os.getenv("DEV_MODE", "0").lower() in ("1", "true", "yes")
        
        params = cls(
            input_path=input_path,
            output_path=output_path,
            dev_mode=dev_mode
        )
        
        # If not in dev mode, we need to validate production params
        if dev_mode:
            return params

        params.query = os.getenv("QUERY", "")
        params.query_signature = os.getenv("QUERY_SIGNATURE", "")
        
        # Parse and validate query params
        query_params_env = os.getenv("QUERY_PARAMS", "")
        if query_params_env:
            try:
                params.query_params = json.loads(query_params_env)
            except json.JSONDecodeError:
                error_msg = f"Error: QUERY_PARAMS is not valid JSON: {query_params_env}"
                print(error_msg)
                raise ContainerParamError(error_msg)
        
        # Parse and validate job and refiner IDs
        job_id_env = os.getenv("COMPUTE_JOB_ID", "")
        refiner_id_env = os.getenv("DATA_REFINER_ID", "")
        
        if job_id_env and refiner_id_env:
            try:
                params.compute_job_id = int(job_id_env)
                params.data_refiner_id = int(refiner_id_env)
            except ValueError:
                error_msg = f"Error: COMPUTE_JOB_ID or DATA_REFINER_ID is not an integer: {job_id_env}, {refiner_id_env}"
                print(error_msg)
                raise ContainerParamError(error_msg)
        
        return params
    
    def validate_production_mode(self) -> bool:
        """Validate parameters required for production mode."""
        if not self.query or not self.query_signature:
            print("Error: Missing required QUERY or QUERY_SIGNATURE environment variables")
            print("Set DEV_MODE=1 to use local database file without query execution")
            return False
            
        if not self.compute_job_id or not self.data_refiner_id:
            print("Error: Missing required COMPUTE_JOB_ID or DATA_REFINER_ID environment variables")
            return False
            
        return True
    
    @property
    def db_path(self) -> Path:
        """Get the full path to the SQLite database."""
        return self.input_path / "query_results.db"
    
    @property
    def stats_path(self) -> Path:
        """Get the full path to the output stats file."""
        return self.output_path / "stats.json" 