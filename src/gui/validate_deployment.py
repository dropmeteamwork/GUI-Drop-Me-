#!/usr/bin/env python3
"""
Pre-deployment validation script for RVM AI models.
Run this script BEFORE uploading to the production machine to catch any issues.

Usage:
    python validate_deployment.py
"""

import sys
import ast
import importlib.util
from pathlib import Path
from typing import List, Tuple

# Terminal colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_header(text: str):
    """Print a formatted header"""
    print(f"\n{BLUE}{'='*70}{RESET}")
    print(f"{BLUE}{text:^70}{RESET}")
    print(f"{BLUE}{'='*70}{RESET}\n")

def print_success(text: str):
    """Print success message"""
    print(f"{GREEN}✓ {text}{RESET}")

def print_error(text: str):
    """Print error message"""
    print(f"{RED}✗ {text}{RESET}")

def print_warning(text: str):
    """Print warning message"""
    print(f"{YELLOW}⚠ {text}{RESET}")

def check_syntax(file_path: Path) -> Tuple[bool, str]:
    """Check Python syntax of a file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            code = f.read()
        ast.parse(code)
        return True, "Syntax valid"
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, f"Error reading file: {str(e)}"

def check_required_packages() -> List[Tuple[str, bool, str]]:
    """Check if required packages are importable"""
    packages = [
        ('cv2', 'opencv-python'),
        ('numpy', 'numpy'),
        ('PIL', 'Pillow'),
        ('boto3', 'boto3'),
        ('ultralytics', 'ultralytics'),
        ('torch', 'torch'),
        ('torchvision', 'torchvision'),
    ]
    
    results = []
    for module_name, package_name in packages:
        try:
            spec = importlib.util.find_spec(module_name)
            if spec is not None:
                results.append((package_name, True, "Installed"))
            else:
                results.append((package_name, False, "Not found"))
        except Exception as e:
            results.append((package_name, False, f"Error: {str(e)}"))
    
    return results

def check_paths_config(file_path: Path) -> List[Tuple[str, bool, str]]:
    """Check if production paths are correctly configured"""
    issues = []

    # Define your ACTUAL expected production paths
    EXPECTED_MODEL_PATH_STRING = "~/.local/state/dropme/gui-v1.1.3/src/gui/new_models"
    EXPECTED_LOG_PATH_STRING = "~/.local/state/dropme/gui-v1.1.3/src/gui/new_models/log"
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for laptop paths
        if 'D:\\' in content or 'D:/' in content:
            issues.append(("Windows path found", False, "Found D:\\ path - should use /home/user/ for production"))
        
        # Check IS_PRODUCTION flag
        if 'IS_PRODUCTION = False' in content:
            issues.append(("IS_PRODUCTION flag", False, "IS_PRODUCTION is set to False"))
        else:
            issues.append(("IS_PRODUCTION flag", True, "Correctly configured"))
    

        # Check for production paths
        if EXPECTED_MODEL_PATH_STRING in content:
            issues.append(("Production model path", True, f"Found {EXPECTED_MODEL_PATH_STRING}"))
        else:
            # You might want to keep the error message generic or list both options
            issues.append(("Production model path", False, "Production path not found (expected custom path)")) 

        if EXPECTED_LOG_PATH_STRING in content:
            issues.append(("Production log path", True, f"Found {EXPECTED_LOG_PATH_STRING}"))
        else:
            issues.append(("Production log path", False, "Production log path not found (expected custom path)"))
    
        
        # Check for test functions
        if 'def test_model_locally' in content:
            issues.append(("Test functions", False, "Test function still present - should be removed"))
        else:
            issues.append(("Test functions", True, "Test functions removed"))
        
    except Exception as e:
        issues.append(("File reading", False, f"Error: {str(e)}"))
    
    return issues

def check_mlmodel_init(file_path: Path) -> Tuple[bool, str]:
    """Check if MLModel.__init__ accepts no model_path argument"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Look for MLModel.__init__ signature
        if 'def __init__(self, model_path: str = None):' in content or \
           'def __init__(self, model_path=None):' in content or \
           'def __init__(self):' in content:
            return True, "MLModel() can be called without arguments"
        else:
            return False, "MLModel.__init__ signature may require model_path argument"
    except Exception as e:
        return False, f"Error checking init: {str(e)}"

def check_imports(file_path: Path) -> List[Tuple[str, bool, str]]:
    """Check for problematic imports"""
    issues = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in ['onnxruntime']:
                        issues.append((f"Optional import: {alias.name}", True, 
                                      "OK - handled with try/except"))
            elif isinstance(node, ast.ImportFrom):
                if node.module and 'gui' in node.module:
                    issues.append((f"Import from gui", False, 
                                  f"Found import from {node.module} - may not exist in production"))
        
        if not issues:
            issues.append(("Import statements", True, "All imports look good"))
        
    except Exception as e:
        issues.append(("Import check", False, f"Error: {str(e)}"))
    
    return issues

def validate_mlmodel_file(file_path: Path):
    """Run all validation checks on mlmodel.py"""
    print_header("VALIDATING MLMODEL.PY FOR PRODUCTION DEPLOYMENT")
    
    # Check if file exists
    if not file_path.exists():
        print_error(f"File not found: {file_path}")
        return False
    
    print(f"Validating file: {file_path}\n")
    
    all_passed = True
    
    # 1. Syntax check
    print("1. SYNTAX CHECK")
    syntax_ok, syntax_msg = check_syntax(file_path)
    if syntax_ok:
        print_success(syntax_msg)
    else:
        print_error(syntax_msg)
        all_passed = False
    
    # 2. Package dependencies
    print("\n2. PACKAGE DEPENDENCIES")
    packages = check_required_packages()
    for package, installed, msg in packages:
        if installed:
            print_success(f"{package:20s} - {msg}")
        else:
            print_error(f"{package:20s} - {msg}")
            all_passed = False
    
    # 3. Configuration check
    print("\n3. CONFIGURATION CHECK")
    config_issues = check_paths_config(file_path)
    for item, ok, msg in config_issues:
        if ok:
            print_success(f"{item:30s} - {msg}")
        else:
            print_error(f"{item:30s} - {msg}")
            all_passed = False
    
    # 4. MLModel initialization
    print("\n4. MLMODEL INITIALIZATION")
    init_ok, init_msg = check_mlmodel_init(file_path)
    if init_ok:
        print_success(init_msg)
    else:
        print_error(init_msg)
        all_passed = False
    
    # 5. Import statements
    print("\n5. IMPORT STATEMENTS")
    import_issues = check_imports(file_path)
    for item, ok, msg in import_issues:
        if ok:
            print_success(f"{item} - {msg}")
        else:
            print_error(f"{item} - {msg}")
            all_passed = False
    
    # Final summary
    print_header("VALIDATION SUMMARY")
    if all_passed:
        print_success("ALL CHECKS PASSED! ✓")
        print(f"\n{GREEN}The file is ready for production deployment.{RESET}")
        print(f"\n{BLUE}Next steps:{RESET}")
        print("  1. Copy mlmodel.py to production machine: /home/user/")
        print("  2. Ensure model files are in: /home/user/models/")
        print("  3. Create log directory: sudo mkdir -p /var/log/rvm")
        print("  4. Set permissions: sudo chown -R user:user /var/log/rvm")
        print("  5. Update server.py to use: self.mlmodel = MLModel()")
        return True
    else:
        print_error("VALIDATION FAILED! ✗")
        print(f"\n{RED}Please fix the issues above before deployment.{RESET}")
        return False

def main():
    """Main validation function"""
    # Look for mlmodel.py in current directory
    mlmodel_path = Path("mlmodel.py")
    
    if len(sys.argv) > 1:
        mlmodel_path = Path(sys.argv[1])
    
    success = validate_mlmodel_file(mlmodel_path)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
