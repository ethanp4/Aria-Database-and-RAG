if (Get-Command "docker" -ErrorAction SilentlyContinue) {
    Write-Host "Docker is installed. Running docker compose..."
    docker compose -f docker-compose.yml up --build 
} else {
    $venv_dir = "./venv"
    if (Test-Path -Path $venv_dir -PathType Container) {
        ./venv/Scripts/activate
        cd .\aria_project
        python manage.py runserver
    } else {
        python -m venv $venv_dir
        ./venv/Scripts/activate
        pip install -r .\requirements.txt
        cd ./aria_project
        python manage.py runserver
    }
}