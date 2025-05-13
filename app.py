from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from pymongo import MongoClient
from werkzeug.security import generate_password_hash
import pytz

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from bson import ObjectId
from werkzeug.utils import secure_filename

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
inquiries_collection = db['inquiries']
revenue_collection = db['revenue']

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, user_id, first_name, email, admin):
        self.id = user_id
        self.first_name = first_name
        self.email = email
        self.admin = admin

    def get_id(self):
        return self.id
    
@login_manager.user_loader
def load_user(user_id):
    try:
        user_data = users_collection.find_one({"_id": ObjectId(user_id)})
        if user_data:
            return User(user_id, user_data['first_name'], user_data['email'], user_data.get('admin', False)) 
    except Exception as e:
        print(f"Error loading user: {e}")
    return None

@login_manager.unauthorized_handler
def unauthorized():
    return redirect(url_for('login'))

@app.route('/')
def index():
    cars = list(cars_collection.find())
    return render_template('index.html' , cars=cars)

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
            # Create user with string ID to match what load_user expects
            user_id = str(user_data['_id'])
            user = User(user_id, user_data['first_name'], user_data['email'], user_data.get('admin', False))
            login_user(user)
            asian_time_zone = pytz.timezone('Asia/Kolkata')
            current_time = datetime.now(asian_time_zone).strftime("%Y-%m-%d %H:%M:%S")
            users_collection.update_one({"_id": ObjectId(user_id)}, {"$set": {"last_login": current_time}})
            flash('Login successful!', 'success')         
            print("User logged in:", user.first_name)   
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
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form['email']
        phone = request.form['phone']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return redirect(url_for('register'))
        
        if users_collection.find_one(
            {
                "email": email
            }
        ):
            flash('Email already exists', 'danger')
            return redirect(url_for('register'))
        #hashed_password = generate_password_hash(password)
        user = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone": phone,
            "password": password,
            "admin": False
        }
        users_collection.insert_one(user)
        flash('Registration successful! You can now log in.', 'success')
        return redirect(url_for('login'))
    if request.method == 'GET':
        if current_user.is_authenticated:
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
    print("User logged in:", current_user.first_name)
    print("Admin status:", current_user.admin)
    cars = list(cars_collection.find())
    booked_cars = list(cars_collection.find({"booked": True}))
    inquiries = list(inquiries_collection.find({"status": "pending"}))
    if current_user.admin:
        inquiries = list(inquiries_collection.find())
    else:
        inquiries = list(inquiries_collection.find({"user_id": str(current_user.id)}))
    revenue = list(revenue_collection.find(
        {
            "created_at": {
                "$gte": datetime.now() - timedelta(days=30)
            }
        }
    ))
    total_revenue = sum(item.get('amount', 0) for item in revenue)
    if current_user.admin:
        return render_template('admin_dashboard.html', cars=cars, user=current_user, booked_cars=booked_cars, inquiries=inquiries, revenue=total_revenue)
    return render_template('user_dashboard.html', cars=cars, user=current_user, inquiries=inquiries)

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
        request.form['name']
        request.form['email']
        request.form['message']
    
    return render_template('contact.html')

# Define allowed extensions for image uploads
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/admin/cars/add', methods=['GET', 'POST'])
@login_required
def add_car():
    if not current_user.admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        # Get form data
        name = request.form.get('name')
        category = request.form.get('category')
        price = request.form.get('price')
        status = request.form.get('status')
        year = request.form.get('year')
        fuel_type = request.form.get('fuel_type')
        description = request.form.get('description', '')
        
        # Process image upload
        car_image = request.files.get('car_image')
        image_filename = None
        
        if car_image and allowed_file(car_image.filename):
            # Secure the filename
            image_filename = secure_filename(car_image.filename)
            
            # Create timestamp to make filename unique
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            image_filename = f"{timestamp}_{image_filename}"
            
            # Save the file
            upload_folder = os.path.join(app.static_folder, 'images', 'cars')
            
            # Create directory if it doesn't exist
            if not os.path.exists(upload_folder):
                os.makedirs(upload_folder)
                
            car_image.save(os.path.join(upload_folder, image_filename))
            image_path = f"/static/images/cars/{image_filename}"
        else:
            # Use default image if none provided
            image_path = "/static/images/default_car.jpg"
        
        # Create car document
        new_car = {
            "name": name,
            "category": category,
            "price_per_day": int(price),
            "status": status,
            "booked": True if status == "Booked" else False,
            "year": int(year),
            "fuel_type": fuel_type,
            "description": description,
            "image": image_path,
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        
        # Insert into database
        result = cars_collection.insert_one(new_car)
        
        if result.inserted_id:
            flash('Vehicle added successfully!', 'success')
            return redirect(url_for('admin_cars'))
        else:
            flash('Failed to add vehicle. Please try again.', 'danger')
    
    return render_template('admin_add_car.html', user=current_user)

@app.route('/admin/cars')
@login_required
def admin_cars():
    if not current_user.admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('dashboard'))
        
    cars = list(cars_collection.find())
    return render_template('admin_cars.html', cars=cars, user=current_user)

@app.route('/admin/cars/delete', methods=['POST'])
@login_required
def delete_car():
    if not current_user.admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('dashboard'))
    
    car_id = request.form.get('car_id')
    
    if not car_id:
        flash('Car ID is required', 'danger')
        return redirect(url_for('admin_cars'))
    
    try:
        car = cars_collection.find_one({"_id": ObjectId(car_id)})
        if not car:
            flash('Car not found', 'danger')
            return redirect(url_for('admin_cars'))
        
        # Delete the car image if it exists and is not the default image
        if car.get('image') and 'default_car.jpg' not in car['image']:
            try:
                # Strip the /static/ prefix to get the correct file path
                image_path = car['image'].replace('/static', app.static_folder)
                if os.path.exists(image_path):
                    os.remove(image_path)
            except Exception as e:
                print(f"Error deleting image: {e}")
        
        # Delete the car from the database
        result = cars_collection.delete_one({"_id": ObjectId(car_id)})
        
        if result.deleted_count:
            flash('Vehicle deleted successfully', 'success')
        else:
            flash('Failed to delete vehicle', 'danger')
            
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')
    
    return redirect(url_for('admin_cars'))

@app.route('/admin/cars/view/<car_id>')
@login_required
def view_car(car_id):
    if not current_user.admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        car = cars_collection.find_one({"_id": ObjectId(car_id)})
        if not car:
            flash('Car not found', 'danger')
            return redirect(url_for('admin_cars'))
            
        return render_template('admin_view_car.html', car=car, user=current_user)
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')
        return redirect(url_for('admin_cars'))

@app.route('/admin/cars/edit/<car_id>', methods=['GET', 'POST'])
@login_required
def edit_car(car_id):
    if not current_user.admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        car = cars_collection.find_one({"_id": ObjectId(car_id)})
        if not car:
            flash('Car not found', 'danger')
            return redirect(url_for('admin_cars'))
        
        if request.method == 'POST':
            # Get form data
            name = request.form.get('name')
            category = request.form.get('category')
            price = request.form.get('price')
            status = request.form.get('status')
            year = request.form.get('year')
            fuel_type = request.form.get('fuel_type')
            description = request.form.get('description', '')
            
            # Process image upload
            car_image = request.files.get('car_image')
            image_path = car.get('image')  # Use existing image path by default
            
            if car_image and car_image.filename and allowed_file(car_image.filename):
                # Secure the filename
                image_filename = secure_filename(car_image.filename)
                
                # Create timestamp to make filename unique
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                image_filename = f"{timestamp}_{image_filename}"
                
                # Save the file
                upload_folder = os.path.join(app.static_folder, 'images', 'cars')
                
                # Create directory if it doesn't exist
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                    
                car_image.save(os.path.join(upload_folder, image_filename))
                image_path = f"/static/images/cars/{image_filename}"
                
                # Delete the old image if it's not the default
                if car.get('image') and 'default_car.jpg' not in car['image']:
                    try:
                        old_image_path = car['image'].replace('/static', app.static_folder)
                        if os.path.exists(old_image_path):
                            os.remove(old_image_path)
                    except Exception as e:
                        print(f"Error deleting old image: {e}")
            
            # Update car document
            update_data = {
                "name": name,
                "category": category,
                "price_per_day": int(price),
                "status": status,
                "booked": True if status == "Booked" else False,
                "year": int(year),
                "fuel_type": fuel_type,
                "description": description,
                "image": image_path,
                "updated_at": datetime.now()
            }
            
            # Update in database
            result = cars_collection.update_one(
                {"_id": ObjectId(car_id)}, 
                {"$set": update_data}
            )
            
            if result.modified_count:
                flash('Vehicle updated successfully!', 'success')
                return redirect(url_for('admin_cars'))
            else:
                flash('No changes were made to the vehicle.', 'info')
                
        return render_template('admin_edit_car.html', car=car, user=current_user)
        
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')
        return redirect(url_for('admin_cars'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=80)