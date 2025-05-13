from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
import pytz

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from bson import ObjectId

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.getenv('SECRET_KEY', 'default_secret_key')

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
# Initialize MongoDB client
mongo_client = MongoClient(MONGO_URI)
db = mongo_client['alexcars']
users_collection = db['users']
cars_collection = db['cars']

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, user_id, username, email, admin):
        self.id = user_id
        self.username = username
        self.email = email
        self.admin = admin

    def get_id(self):
        return self.id
    
@login_manager.user_loader
def load_user(user_id):
    user_data = users_collection.find_one({"_id": ObjectId(user_id)})
    if user_data:
        return User(user_data['_id'], user_data['username'], user_data['email'], user_data.get('admin', False))
    return None

@login_manager.unauthorized_handler
def unauthorized():
    return redirect(url_for('login'))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        return render_template('login.html')
    
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user_data = users_collection.find_one({"email": email})
        if user_data and user_data['password'] == password:
            user = User(str(user_data['_id']), user_data['username'], user_data['email'], user_data.get('admin', False))
            login_user(user)
            asian_time_zone = pytz.timezone('Asia/Kolkata')
            current_time = datetime.now(asian_time_zone).strftime("%Y-%m-%d %H:%M:%S")
            users_collection.update_one({"_id": ObjectId(user.id)}, {"$set": {"last_login": current_time}})
            flash('Login successful!', 'success')         
            print("User logged in:", user.username)   
            return redirect(url_for('dashboard'))
        else:
            print("Invalid login attempt:", email)
            flash('Invalid username or password', 'danger')
            return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return redirect(url_for('register'))

        if users_collection.find_one({"username": username}):
            flash('Username already exists', 'danger')
            return redirect(url_for('register'))

        asia_time_zone = pytz.timezone('Asia/Kolkata')
        current_time = datetime.now(asia_time_zone).strftime("%Y-%m-%d %H:%M:%S")

        #hashed_password = generate_password_hash(password)
        result = users_collection.insert_one({
            "username": username,
            "email": email,
            "password": password,
            "created_at": current_time,
            "last_login": None,
            "admin": False
        })
        
        user = User(result.inserted_id, username, email, False)
        login_user(user)
        
        return redirect(url_for('dashboard'))

    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    cars = list(cars_collection.find())
    return render_template('dashboard.html', cars=cars, user=current_user)

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if not current_user.admin:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('dashboard'))
    
    users = list(users_collection.find())
    return render_template('admin_dashboard.html', users=users, user=current_user)

@app.route('/admin/cars')
@login_required
def admin_cars():
    if not current_user.admin:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('dashboard'))
    
    cars = list(cars_collection.find())
    return render_template('admin_cars.html', cars=cars, user=current_user)

@app.route('/admin/cars/add', methods=['GET', 'POST'])
@login_required
def add_car():
    if not current_user.admin:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        make = request.form['make']
        model = request.form['model']
        year = request.form['year']
        price = request.form['price']
        description = request.form['description']
        available = request.form.get('available', 'off') == 'on'

        asia_time_zone = pytz.timezone('Asia/Kolkata')
        current_time = datetime.now(asia_time_zone).strftime("%Y-%m-%d %H:%M:%S")
        cars_collection.insert_one({
            "make": make,
            "model": model,
            "year": year,
            "price": price,
            "description": description,
            "created_at": current_time,
            "updated_at": current_time,
            "available": True if available == 'on' else False
        })     
        flash('Car added successfully!', 'success')
        return redirect(url_for('admin_cars'))
    
@app.route('/admin/cars/edit/<car_id>', methods=['GET', 'POST'])
@login_required
def edit_car(car_id):
    if not current_user.admin:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('dashboard'))
    
    car = cars_collection.find_one({"_id": ObjectId(car_id)})
    if not car:
        flash('Car not found', 'danger')
        return redirect(url_for('admin_cars'))
    if request.method == 'POST':
        make = request.form['make']
        model = request.form['model']
        year = request.form['year']
        price = request.form['price']
        description = request.form['description']
        available = request.form.get('available', 'off') == 'on'

        asia_time_zone = pytz.timezone('Asia/Kolkata')
        current_time = datetime.now(asia_time_zone).strftime("%Y-%m-%d %H:%M:%S")
        cars_collection.update_one({"_id": ObjectId(car_id)}, {
            "$set": {
                "make": make,
                "model": model,
                "year": year,
                "price": price,
                "description": description,
                "updated_at": current_time,
                "available": True if available == 'on' else False
            }
        })
        flash('Car updated successfully!', 'success')
        return redirect(url_for('admin_cars'))
    
    return render_template('edit_car.html', car=car, user=current_user)

@app.route('/admin/cars/delete/<car_id>', methods=['POST'])
@login_required
def delete_car(car_id):
    if not current_user.admin:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('dashboard'))
    
    cars_collection.delete_one({"_id": ObjectId(car_id)})
    flash('Car deleted successfully!', 'success')
    return redirect(url_for('admin_cars'))

@app.route('/admin/users', methods=['GET'])
@login_required
def admin_users():
    if not current_user.admin:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('dashboard'))
    
    users = list(users_collection.find())
    return render_template('admin_users.html', users=users, user=current_user)

@app.route('/admin/users/edit/<user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    if not current_user.admin:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('dashboard'))
    
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        admin = 'admin' in request.form

        users_collection.update_one({"_id": ObjectId(user_id)}, {
            "$set": {
                "username": username,
                "email": email,
                "admin": admin
            }
        })
        flash('User updated successfully!', 'success')
        return redirect(url_for('admin_users'))
    
@app.route('/admin/users/delete/<user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.admin:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('dashboard'))
    
    users_collection.delete_one({"_id": ObjectId(user_id)})
    flash('User deleted successfully!', 'success')
    return redirect(url_for('admin_users'))

@app.route('/about', methods=['GET'])
def about():
    return render_template('about.html')

@app.route('/cars', methods=['GET'])
def cars():
    cars = list(cars_collection.find())
    return render_template('cars.html', cars=cars)

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        message = request.form['message']

        flash('Message sent successfully!', 'success')
        return redirect(url_for('contact'))
    
    return render_template('contact.html')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=80)