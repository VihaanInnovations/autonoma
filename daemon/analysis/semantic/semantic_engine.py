from pathlib import Path
from typing import Optional, List, Dict, Any, Union
import logging
from .lsp_client import LSPClient

logger = logging.getLogger(__name__)

class SemanticEngine:
    """
    High-level engine for semantic code analysis using LSP.
    """
    
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self._lsp_client: Optional[LSPClient] = None
        
    def start(self):
        """Start the LSP client."""
        if not self._lsp_client:
            try:
                self._lsp_client = LSPClient(cwd=str(self.repo_path))
                self._lsp_client.start()
                logger.info("SemanticEngine (LSP) started.")
            except Exception as e:
                logger.error(f"Failed to start SemanticEngine: {e}")
                self._lsp_client = None
                
    def stop(self):
        """Stop the LSP client."""
        if self._lsp_client:
            self._lsp_client.stop()
            self._lsp_client = None
            
    def analyze_file_symbols(self, file_path: Union[str, Path]) -> List[Dict]:
        """
        Get all symbols (functions, classes, variables) in a file.
        """
        if not self._lsp_client:
            logger.warning("SemanticEngine not running.")
            return []
            
        file_path = Path(file_path)
        try:
            # open file first to ensure LSP knows about it
            content = file_path.read_text(encoding='utf-8')
            self._lsp_client.did_open(str(file_path), content)
            
            # query symbols
            return self._lsp_client.document_symbol(str(file_path))
        except Exception as e:
            logger.error(f"Failed to analyze symbols for {file_path}: {e}")
            return []

    def get_definitions(self, file_path: Union[str, Path]) -> List[Dict]:
        """
        Simplified helper: Returns a list of 'definitions' (Class/Function/Variable)
        found in the file.
        """
        symbols = self.analyze_file_symbols(file_path)
        definitions = []
        
        def traverse(syms):
            for s in syms:
                # LSP SymbolKind: 5=Class, 12=Function, 13=Variable, 6=Method
                kind = s.get('kind')
                name = s.get('name')
                
                if kind in [5, 6, 12, 13]: 
                    definitions.append({
                        'name': name,
                        'kind': kind,
                        'range': s.get('location', {}).get('range', {}) if 'location' in s else s.get('range', {})
                    })
                
                if 'children' in s:
                    traverse(s['children'])
                    
        traverse(symbols)
        return definitions

    def is_variable_definition(self, file_path: Union[str, Path], line: int, name: str) -> bool:
        """
        Verifies if a specific variable name is semantically defined at the given line.
        Useful for validating regex matches.
        
        Args:
            file_path: Path to the file.
            line: 0-indexed line number (LSP uses 0-based).
            name: Variable name to check.
        """
        definitions = self.get_definitions(file_path)
        for d in definitions:
            # Check name match
            if d['name'] != name:
                continue
                
            # Check kind (Variable=13, Constant=14, Field=8, Property=7)
            # We usually care about Variables or Constants for SEC001/002
            if d['kind'] not in [13, 14, 8, 7]:
                continue
                
            # Check line match
            # LSP ranges are start/end. The definition should start on the line.
            rng = d['range']
            if not rng: continue
            
            start_line = rng.get('start', {}).get('line')
            if start_line == line:
                return True
                
                return True
                
        return False

    def find_references(self, file_path: Union[str, Path], line: int, character: int) -> List[Dict]:
        """
        Find references to the symbol at the given position.
        
        Args:
            file_path: Path to the file.
            line: 0-indexed line number.
            character: 0-indexed character offset.
        """
        if not self._lsp_client:
            return []
            
        uri = f"file:///{str(file_path).replace(os.sep, '/')}"
        params = {
            "textDocument": { "uri": uri },
            "position": { "line": line, "character": character },
            "context": { "includeDeclaration": True }
        }
        try:
            return self._lsp_client.send_request("textDocument/references", params) or []
        except Exception as e:
            logger.error(f"Failed to find references: {e}")
            return []
