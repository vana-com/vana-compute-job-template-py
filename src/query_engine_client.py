import os
import time
import logging
import requests
from typing import Any, Dict, Optional, List
from dataclasses import dataclass
import contextlib

logger = logging.getLogger(__name__)

@dataclass
class QueryResult:
    """Container for query execution results"""
    success: bool
    data: Dict[str, Any]
    file_path: Optional[str] = None
    error: Optional[str] = None
    status_code: Optional[int] = None


class QueryError(Exception):
    """Exception raised for query execution errors"""
    def __init__(self, message: str, status_code: Optional[int] = None, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class QueryEngineClient:
    """Client for executing queries against the Vana Query Engine"""

    def __init__(
        self, 
        query: str, 
        query_signature: str, 
        query_results_path: str, 
        timeout_seconds: int = 150,
        poll_interval: int = 5,
        query_engine_url: Optional[str] = None
    ):
        """
        Initialize the QueryEngineClient
        
        Args:
            query: The query to execute
            query_signature: Signature for authenticating the query
            query_results_path: Path where query results will be saved
            timeout_seconds: Maximum time to wait for results (default: 150 seconds)
            poll_interval: Seconds between status checks (default: 5 seconds)
            query_engine_url: Override the default Query Engine URL
        """
        self.query = query
        self.query_signature = query_signature
        self.query_results_path = query_results_path
        self.timeout_seconds = timeout_seconds
        self.poll_interval = poll_interval
        self.query_engine_url = query_engine_url or os.getenv("QUERY_ENGINE_URL", "https://query.vana.org")
        
        logger.info("QueryEngineClient initialized")

    def execute_query(self, job_id: int, refiner_id: int, params: Optional[List[Any]] = None) -> QueryResult:
        """
        Execute a query and wait for results
        
        Args:
            job_id: The compute job ID
            refiner_id: The data refiner ID
            params: Optional parameters to include with the query
            
        Returns:
            QueryResult object containing success status and result data
            
        Example:
            >>> client = QueryEngineClient(query, signature, "output/results.db")
            >>> result = client.execute_query(21, 12, [1, 2, 3])
            >>> if result.success:
            >>>     print(f"Query successful, results at: {result.file_path}")
        """
        try:            
            # Submit the query
            query_id = self._submit_query(job_id, refiner_id, params)
            
            # Poll for results
            return self._poll_until_complete(query_id)
            
        except QueryError as e:
            logger.error(f"Query error: {e.message}")
            return QueryResult(
                success=False,
                data={},
                error=e.message,
                status_code=e.status_code
            )
        except Exception as e:
            error_msg = f"Unexpected error executing query: {str(e)}"
            logger.exception(error_msg)
            return QueryResult(
                success=False,
                data={},
                error=error_msg,
                status_code=500
            )

    def _submit_query(self, job_id: int, refiner_id: int, params: Optional[List[Any]] = None) -> str:
        """
        Submit a query to the Query Engine
        
        Returns:
            Query ID for tracking
            
        Raises:
            QueryError: If the query submission fails
        """
        url = f"{self.query_engine_url}/query"
        headers = self._get_headers()
        data = {
            "query": self.query,
            "params": params or [],
            "refiner_id": refiner_id,
            "job_id": str(job_id)
        }
        
        logger.info(f"Submitting query: {self.query}")
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            
            response_data = response.json()
            query_id = response_data.get("query_id", "")
            
            if not query_id:
                raise QueryError("No query ID returned from server", 500)
                
            logger.info(f"Query submitted successfully with ID: {query_id}")
            return query_id
            
        except requests.HTTPError as e:
            error_detail = self._extract_error_details(e.response)
            raise QueryError(
                f"HTTP error submitting query: {error_detail}",
                e.response.status_code
            )
        except requests.ConnectionError as e:
            raise QueryError(f"Connection error: {str(e)}", 502)
        except requests.Timeout as e:
            raise QueryError("Request timed out after 30 seconds", 504)
        except Exception as e:
            raise QueryError(f"Error submitting query: {str(e)}", 500)

    def _poll_until_complete(self, query_id: str) -> QueryResult:
        """
        Poll for query completion and download results when ready
        
        Args:
            query_id: The ID of the query to poll
            
        Returns:
            QueryResult object with outcome
            
        Raises:
            QueryError: If polling fails or times out
        """
        url = f"{self.query_engine_url}/query/{query_id}"
        headers = self._get_headers()
        
        start_time = time.time()
        logger.info(f"Polling for results of query {query_id}")
        
        while (time.time() - start_time) < self.timeout_seconds:
            try:
                response = requests.get(url, headers=headers, timeout=30)
                
                if response.status_code == 404:
                    raise QueryError(f"Query {query_id} not found", 404)
                
                response.raise_for_status()
                response_data = response.json()
                
                query_status = response_data.get("query_status", "")
                logger.info(f"Query {query_id} status: {query_status}")
                
                if query_status == "success":
                    logger.info(f"Query {query_id} completed successfully")
                    
                    # Download results if URL is provided
                    results_url = response_data.get("query_results")
                    if results_url:
                        downloaded_path = self._download_results(results_url)
                        response_data["downloaded_path"] = downloaded_path
                    
                    return QueryResult(
                        success=True,
                        data=response_data,
                        file_path=downloaded_path if results_url else None
                    )
                
                elif query_status == "failed":
                    error_msg = f"Query {query_id} failed"
                    logger.error(error_msg)
                    return QueryResult(
                        success=False,
                        data=response_data,
                        error=error_msg
                    )
                
                # Still pending, wait before polling again
                time.sleep(self.poll_interval)
                
            except QueryError:
                # Pass through errors from _extract_error_details
                raise
            except requests.HTTPError as e:
                error_detail = self._extract_error_details(e.response)
                raise QueryError(
                    f"HTTP error polling query: {error_detail}",
                    e.response.status_code
                )
            except requests.ConnectionError as e:
                raise QueryError(f"Connection error polling query: {str(e)}", 502)
            except requests.Timeout as e:
                raise QueryError("Request timed out after 30 seconds", 504)
            except Exception as e:
                raise QueryError(f"Error polling query: {str(e)}", 500)
        
        # If we get here, we've exceeded the timeout
        raise QueryError(
            f"Timeout exceeded ({self.timeout_seconds}s) waiting for query results",
            408
        )

    def _download_results(self, url: str) -> str:
        """
        Download query results to the specified path
        
        Args:
            url: URL to download results from
            
        Returns:
            Path where the results were saved
            
        Raises:
            QueryError: If download fails
        """
        logger.info(f"Downloading query results from {url}")
        
        try:
            headers = self._get_headers()
            
            # Create parent directory if it doesn't exist
            with contextlib.suppress(FileExistsError):
                os.makedirs(os.path.dirname(self.query_results_path), exist_ok=True)
            
            # Stream the download to use less memory
            with requests.get(url, headers=headers, timeout=60, stream=True) as response:
                response.raise_for_status()
                
                # Save the file
                with open(self.query_results_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
            
            logger.info(f"Successfully downloaded query results to {self.query_results_path}")
            return self.query_results_path
                
        except requests.HTTPError as e:
            error_detail = self._extract_error_details(e.response)
            raise QueryError(
                f"HTTP error downloading results: {error_detail}",
                e.response.status_code
            )
        except requests.ConnectionError as e:
            raise QueryError(f"Connection error downloading results: {str(e)}", 502)
        except requests.Timeout as e:
            raise QueryError("Download timed out after 60 seconds", 504)
        except Exception as e:
            raise QueryError(f"Error downloading results: {str(e)}", 500)

    def _get_headers(self) -> Dict[str, str]:
        """Return standard headers for API requests"""
        return {
            "Content-Type": "application/json",
            "X-Query-Signature": self.query_signature
        }
        
    def _extract_error_details(self, response) -> str:
        """Extract detailed error information from a response"""
        status_code = response.status_code
        error_detail = f"Status code: {status_code}"
        
        try:
            error_json = response.json()
            if "detail" in error_json:
                error_detail += f", Detail: {error_json['detail']}"
        except (ValueError, KeyError):
            error_detail += f", Response: {response.text[:100]}"
            
        return error_detail
