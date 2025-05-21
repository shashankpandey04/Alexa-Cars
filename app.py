from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from pymongo import MongoClient
from werkzeug.security import generate_password_hash
import pytz

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from bson import ObjectId
from werkzeug.utils import secure_filename
import time
import threading
import requests

load_dotenv()

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.getenv('SECRET_KEY', 'default_secret_key')

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
mongo_client = MongoClient(MONGO_URI)
db = mongo_client['alexcars']
users_collection = db['users']
cars_collection = db['cars']
inquiries_collection = db['inquiries']
revenue_collection = db['revenue']
bookings_collection = db['bookings']

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

class User(UserMixin):
    def __init__(self, user_id, first_name, email, admin):
        self.id = user_id
        self.first_name = first_name
        self.email = email
        self.admin = admin

    def get_id(self):
        return self.id
    
WEBSITE_STATUS = "ONLINE"
DEPLOYMENT_LINK = os.getenv('DEPLOYMENT_LINK', 'NONE')

@app.before_request
def check_website_status():
    return render_template('no_payment.html'), 503
    if WEBSITE_STATUS == "OFFLINE":
        return render_template('offline.html'), 503
    elif WEBSITE_STATUS == "MAINTENANCE":
        return render_template('maintenance.html'), 503
    
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
            "admin": False,
            "created_at": datetime.now(),
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
    recent_bookings = list(bookings_collection.find({"status": "active"}))
    if current_user.admin:  
        inquiries = list(inquiries_collection.find())
        return render_template('admin_dashboard.html', cars=cars, user=current_user, booked_cars=booked_cars, inquiries=inquiries, revenue=calculate_revenue(),
                            recent_bookings=recent_bookings, active_page='dashboard')
    
    # For regular users
    active_bookings = list(bookings_collection.find({"user_id": current_user.id, "status": "active"}))
    upcoming_bookings = list(bookings_collection.find({"user_id": current_user.id, "status": "upcoming"}))
    past_bookings = list(bookings_collection.find({"user_id": current_user.id, "status": "completed"}))
    user_inquiries = list(inquiries_collection.find({"user_id": current_user.id}))
    
    return render_template('user_dashboard.html', 
                          user=current_user, 
                          active_bookings=active_bookings,
                          upcoming_bookings=upcoming_bookings,
                          past_bookings=past_bookings, 
                          inquiries=user_inquiries)

@app.route('/inquiry', methods=['GET'])
@login_required
def inquiry_form():
    # Get any pre-selected car ID from query params
    selected_car_id = request.args.get('car')
    
    # First get all cars
    all_cars = list(cars_collection.find())
    
    # Get date range from URL parameters if provided
    start_date_param = request.args.get('start_date')
    end_date_param = request.args.get('end_date')
    
    # Check if we have date parameters to filter by
    if start_date_param and end_date_param:
        try:
            # Parse dates to datetime objects
            start_date = datetime.strptime(start_date_param, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_param, '%Y-%m-%d')
            
            # Get all active and upcoming bookings
            active_bookings = list(bookings_collection.find({
                "status": {"$in": ["active", "upcoming"]}
            }))
            
            # Filter out cars that are booked during the requested period
            available_cars = []
            for car in all_cars:
                is_available = True
                
                # Check each booking for this car
                for booking in active_bookings:
                    if booking.get('car_id') and booking.get('car_id') == car.get('_id'):
                        # Parse booking dates
                        try:
                            booking_start = datetime.strptime(booking.get('start_date'), '%Y-%m-%d')
                            booking_end = datetime.strptime(booking.get('end_date'), '%Y-%m-%d')
                            
                            # Check for date overlap
                            if (start_date <= booking_end and end_date >= booking_start):
                                is_available = False
                                break
                        except ValueError:
                            # Skip if dates can't be parsed
                            continue
                
                if is_available:
                    available_cars.append(car)
        except ValueError:
            # If date parsing fails, fall back to simpler filtering
            available_cars = [car for car in all_cars if car.get('status') != 'Booked']
            flash('Invalid date format provided. Showing available cars.', 'warning')
    else:
        # Without date parameters, just filter out cars marked as "Booked"
        available_cars = [car for car in all_cars if car.get('status') != 'Booked']
    
    # If none available, show message
    if not available_cars:
        flash('No cars available for the selected dates. Please try different dates.', 'info')
    
    # If a specific car was requested, verify it's actually available
    selected_car = None
    if selected_car_id:
        selected_car = next((car for car in available_cars if str(car.get('_id')) == selected_car_id), None)
        if not selected_car:
            flash('The selected car is not available for the requested dates.', 'warning')

    return render_template('user_inquiry.html', cars=available_cars, user=current_user, 
                          selected_car=selected_car,
                          start_date=start_date_param,
                          end_date=end_date_param)

@app.route('/inquiry/submit', methods=['POST'])
@login_required
def submit_inquiry():
    try:
        print("Added")
        car_id = request.form.get('car_id')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        pickup_location = request.form.get('pickup_location')
        return_location = request.form.get('return_location')
        message = request.form.get('message', '')
        
        # Get car details
        car = cars_collection.find_one({"_id": ObjectId(car_id)})
        if not car:
            flash('Selected car not found', 'danger')
            return redirect(url_for('inquiry_form'))
        
        # Validate dates
        try:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
            
            # Check that end date is after start date
            if end_date_obj <= start_date_obj:
                flash('End date must be after start date', 'danger')
                return redirect(url_for('inquiry_form', car=car_id, start_date=start_date, end_date=end_date))
                
            # Check that start date is not in the past
            if start_date_obj < datetime.now().replace(hour=0, minute=0, second=0, microsecond=0):
                flash('Start date cannot be in the past', 'danger')
                return redirect(url_for('inquiry_form', car=car_id))
                
            # Calculate rental duration
            days = (end_date_obj - start_date_obj).days
            if days < 1:
                flash('Rental period must be at least 1 day', 'danger')
                return redirect(url_for('inquiry_form', car=car_id, start_date=start_date, end_date=end_date))
                
            # Check if car is already booked for these dates
            # First check bookings with status active or upcoming
            conflicting_bookings = list(bookings_collection.find({
                "car_id": ObjectId(car_id),
                "status": {"$in": ["active", "upcoming"]},
                "$or": [
                    # Case 1: Booking start date falls within requested period
                    {"start_date": {"$gte": start_date, "$lte": end_date}},
                    # Case 2: Booking end date falls within requested period
                    {"end_date": {"$gte": start_date, "$lte": end_date}},
                    # Case 3: Booking spans the entire requested period
                    {"$and": [
                        {"start_date": {"$lte": start_date}},
                        {"end_date": {"$gte": end_date}}
                    ]}
                ]
            }))
            
            # Also check pending inquiries that might be approved soon
            conflicting_inquiries = list(inquiries_collection.find({
                "car_id": ObjectId(car_id),
                "status": "pending",  # Only check pending inquiries
                "$or": [
                    {"start_date": {"$gte": start_date, "$lte": end_date}},
                    {"end_date": {"$gte": start_date, "$lte": end_date}},
                    {"$and": [
                        {"start_date": {"$lte": start_date}},
                        {"end_date": {"$gte": end_date}}
                    ]}
                ]
            }))
            
            if conflicting_bookings:
                flash('This car is already booked for the selected dates. Please choose different dates or another car.', 'warning')
                return redirect(url_for('inquiry_form', start_date=start_date, end_date=end_date))
                
            if conflicting_inquiries:
                flash('There are pending inquiries for this car during the selected dates. Your inquiry will be processed based on availability.', 'info')
                
            # Calculate price
            total_price = days * car['price_per_day']
            
        except ValueError as e:
            flash(f'Invalid date format: {str(e)}', 'danger')
            return redirect(url_for('inquiry_form'))
        
        # Create inquiry
        inquiry = {
            "user_id": current_user.id,
            "car_id": ObjectId(car_id),
            "car_name": car['name'],
            "start_date": start_date,
            "end_date": end_date,
            "days": days,
            "price_per_day": car['price_per_day'],
            "total_price": total_price,
            "pickup_location": pickup_location,
            "return_location": return_location,
            "message": message,
            "status": "pending",
            "created_at": datetime.now(),
            "user_name": f"{current_user.first_name}",
        }
        
        result = inquiries_collection.insert_one(inquiry)
        
        if result.inserted_id:
            flash('Your inquiry has been submitted successfully! We will contact you shortly.', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Failed to submit inquiry. Please try again.', 'danger')
            
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')
    
    return redirect(url_for('inquiry_form'))

@app.route('/inquiry/<inquiry_id>/cancel', methods=['POST'])
@login_required
def cancel_inquiry(inquiry_id):
    try:
        inquiry = inquiries_collection.find_one({"_id": ObjectId(inquiry_id)})
        
        if not inquiry:
            return jsonify({"success": False, "message": "Inquiry not found"})
        
        if inquiry['user_id'] != current_user.id and not current_user.admin:
            return jsonify({"success": False, "message": "You don't have permission to cancel this inquiry"})
        
        result = inquiries_collection.update_one(
            {"_id": ObjectId(inquiry_id)},
            {"$set": {"status": "cancelled"}}
        )
        
        if result.modified_count:
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "message": "Failed to cancel inquiry"})
            
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

def calculate_revenue():
    revenue = list(revenue_collection.find(
        {
            "created_at": {
                "$gte": datetime.now() - timedelta(days=30)
            }
        }
    ))
    total_revenue = sum(item.get('amount', 0) for item in revenue)
    return total_revenue

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
    return render_template('admin_cars.html', cars=cars, user=current_user, active_page='cars')

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
            name = request.form.get('name')
            category = request.form.get('category')
            price = request.form.get('price')
            status = request.form.get('status')
            year = request.form.get('year')
            fuel_type = request.form.get('fuel_type')
            description = request.form.get('description', '')
            
            car_image = request.files.get('car_image')
            image_path = car.get('image')
            
            if car_image and car_image.filename and allowed_file(car_image.filename):

                image_filename = secure_filename(car_image.filename)

                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                image_filename = f"{timestamp}_{image_filename}"
                
                upload_folder = os.path.join(app.static_folder, 'images', 'cars')
                
                if not os.path.exists(upload_folder):
                    os.makedirs(upload_folder)
                    
                car_image.save(os.path.join(upload_folder, image_filename))
                image_path = f"/static/images/cars/{image_filename}"
                
                if car.get('image') and 'default_car.jpg' not in car['image']:
                    try:
                        old_image_path = car['image'].replace('/static', app.static_folder)
                        if os.path.exists(old_image_path):
                            os.remove(old_image_path)
                    except Exception as e:
                        print(f"Error deleting old image: {e}")
            
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
    
@app.route('/admin/inquiries')
@login_required
def admin_inquiries():
    if not current_user.admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('dashboard'))
    
    inquiries = list(inquiries_collection.find())
    pending_inquiries = list(inquiries_collection.find({"status": "pending"}))
    approved_inquiries = list(inquiries_collection.find({"status": "approved"}))
    today_inquiries = list(inquiries_collection.find({"status": "pending", "created_at": {"$gte": datetime.now() - timedelta(days=1)}}))
    response_rate = 0
    if inquiries:
        response_rate = (len(approved_inquiries) / len(inquiries)) * 100
    return render_template('admin_inquiries.html', 
                          inquiries=inquiries, 
                          user=current_user, 
                          pending_inquiries=pending_inquiries, 
                          approved_inquiries=approved_inquiries, 
                          today_inquiries=today_inquiries, 
                          response_rate=response_rate,
                          active_page='inquiries')


@app.route('/admin/users')
@login_required
def admin_users():
    if not current_user.admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('dashboard'))
    
    # Get query parameters for filtering and sorting
    search_query = request.args.get('search', '')
    status_filter = request.args.get('status', 'all')
    sort_by = request.args.get('sort', 'name_asc')
    
    # Build the query
    query = {}
    if search_query:
        query['$or'] = [
            {'first_name': {'$regex': search_query, '$options': 'i'}},
            {'last_name': {'$regex': search_query, '$options': 'i'}},
            {'email': {'$regex': search_query, '$options': 'i'}}
        ]
    
    if status_filter != 'all':
        if status_filter == 'active':
            query['active'] = True
        elif status_filter == 'inactive':
            query['active'] = False
        elif status_filter == 'admin':
            query['admin'] = True
    
    # Sorting logic
    sort_criteria = []
    if sort_by == 'name_asc':
        sort_criteria = [('first_name', 1)]
    elif sort_by == 'name_desc':
        sort_criteria = [('first_name', -1)]
    elif sort_by == 'email_asc':
        sort_criteria = [('email', 1)]
    elif sort_by == 'email_desc':
        sort_criteria = [('email', -1)]
    elif sort_by == 'recent':
        sort_criteria = [('last_login', -1)]
    
    # Fetch users based on query and sorting
    if sort_criteria:
        users = list(users_collection.find(query).sort(sort_criteria))
    else:
        users = list(users_collection.find(query))
    
    # Statistics for dashboard
    total_users = len(users)
    active_users = sum(1 for user in users if user.get('active', True))
    admin_users = sum(1 for user in users if user.get('admin', False))
    new_users_this_month = sum(1 for user in users if user.get('created_at') and 
                             user['created_at'] >= datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0))
    
    # Return the admin users template with data
    return render_template(
        'admin_users.html',
        users=users,
        user=current_user,
        total_users=total_users,
        active_users=active_users,
        admin_users=admin_users,
        new_users=new_users_this_month,
        search_query=search_query,
        status_filter=status_filter,
        sort_by=sort_by,
        active_page='users'
    )

@app.route('/admin/users/view/<user_id>')
@login_required
def admin_view_user(user_id):
    if not current_user.admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        user_data = users_collection.find_one({"_id": ObjectId(user_id)})
        if not user_data:
            flash('User not found', 'danger')
            return redirect(url_for('admin_users'))
        
        # Get user's bookings
        user_bookings = list(bookings_collection.find({"user_id": user_id}).sort("created_at", -1))
        
        # Get user's inquiries
        user_inquiries = list(inquiries_collection.find({"user_id": user_id}).sort("created_at", -1))
        
        return render_template(
            'admin_view_user.html',
            viewed_user=user_data,
            user=current_user,
            bookings=user_bookings,
            inquiries=user_inquiries
        )
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')
        return redirect(url_for('admin_users'))

@app.route('/admin/users/edit/<user_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_user(user_id):
    if not current_user.admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        user_data = users_collection.find_one({"_id": ObjectId(user_id)})
        if not user_data:
            flash('User not found', 'danger')
            return redirect(url_for('admin_users'))
        
        if request.method == 'POST':
            # Get form data
            first_name = request.form.get('first_name')
            last_name = request.form.get('last_name')
            email = request.form.get('email')
            phone = request.form.get('phone')
            admin_status = True if request.form.get('admin_status') == 'on' else False
            active_status = True if request.form.get('active_status') == 'on' else False
            
            # Check if email exists on another user
            existing_user = users_collection.find_one({"email": email, "_id": {"$ne": ObjectId(user_id)}})
            if existing_user:
                flash('Email already exists for another user', 'danger')
                return render_template('admin_edit_user.html', viewed_user=user_data, user=current_user)
            
            # Prepare update data
            update_data = {
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "phone": phone,
                "admin": admin_status,
                "active": active_status,
                "updated_at": datetime.now()
            }
            
            # Update password if provided
            new_password = request.form.get('new_password')
            if new_password and new_password.strip():
                update_data["password"] = new_password
            
            # Update user in database
            result = users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": update_data}
            )
            
            if result.modified_count:
                flash('User updated successfully', 'success')
                return redirect(url_for('admin_users'))
            else:
                flash('No changes were made to the user', 'info')
        
        return render_template('admin_edit_user.html', viewed_user=user_data, user=current_user)
    
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')
        return redirect(url_for('admin_users'))

@app.route('/admin/users/add', methods=['GET', 'POST'])
@login_required
def admin_add_user():
    if not current_user.admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        # Get form data
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        admin_status = True if request.form.get('admin_status') == 'on' else False
        
        # Validate input
        if not all([first_name, last_name, email, phone, password]):
            flash('All fields are required', 'danger')
            return render_template('admin_add_user.html', user=current_user)
        
        # Check if email exists
        if users_collection.find_one({"email": email}):
            flash('Email already exists', 'danger')
            return render_template('admin_add_user.html', user=current_user)
        
        # Create new user
        new_user = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone": phone,
            "password": password,
            "admin": admin_status,
            "active": True,
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        
        # Insert into database
        result = users_collection.insert_one(new_user)
        
        if result.inserted_id:
            flash('User added successfully', 'success')
            return redirect(url_for('admin_users'))
        else:
            flash('Failed to add user. Please try again.', 'danger')
    
    return render_template('admin_add_user.html', user=current_user)

@app.route('/admin/users/toggle-status/<user_id>/<status_type>', methods=['POST'])
@login_required
def toggle_user_status(user_id, status_type):
    if not current_user.admin:
        return jsonify({"success": False, "message": "Access denied"}), 403
    
    try:
        # Don't allow admins to deactivate themselves
        if user_id == current_user.id and status_type == 'active':
            return jsonify({"success": False, "message": "You cannot deactivate your own account"}), 400
        
        user_data = users_collection.find_one({"_id": ObjectId(user_id)})
        if not user_data:
            return jsonify({"success": False, "message": "User not found"}), 404
        
        if status_type == 'admin':
            new_status = not user_data.get('admin', False)
            status_field = 'admin'
            message = f"Admin status {'granted' if new_status else 'revoked'}"
        elif status_type == 'active':
            new_status = not user_data.get('active', True)
            status_field = 'active'
            message = f"User {'activated' if new_status else 'deactivated'}"
        else:
            return jsonify({"success": False, "message": "Invalid status type"}), 400
        
        result = users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {status_field: new_status, "updated_at": datetime.now()}}
        )
        
        if result.modified_count:
            return jsonify({"success": True, "message": message, "new_status": new_status})
        else:
            return jsonify({"success": False, "message": "No changes were made"})
            
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/admin/users/delete/<user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if not current_user.admin:
        return jsonify({"success": False, "message": "Access denied"}), 403
    
    try:
        # Don't allow admins to delete themselves
        if user_id == current_user.id:
            return jsonify({"success": False, "message": "You cannot delete your own account"}), 400
        
        user_data = users_collection.find_one({"_id": ObjectId(user_id)})
        if not user_data:
            return jsonify({"success": False, "message": "User not found"}), 404
        
        # Check if user has any bookings or inquiries
        bookings = bookings_collection.count_documents({"user_id": user_id})
        inquiries = inquiries_collection.count_documents({"user_id": user_id})
        
        if bookings > 0 or inquiries > 0:
            # Instead of deleting, mark as inactive
            result = users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"active": False, "updated_at": datetime.now()}}
            )
            
            if result.modified_count:
                return jsonify({
                    "success": True, 
                    "message": "User has bookings or inquiries and cannot be deleted. User has been deactivated instead.",
                    "deactivated": True
                })
            else:
                return jsonify({"success": False, "message": "Failed to deactivate user"})
        else:
            # Delete the user if no bookings or inquiries
            result = users_collection.delete_one({"_id": ObjectId(user_id)})
            
            if result.deleted_count:
                return jsonify({"success": True, "message": "User deleted successfully"})
            else:
                return jsonify({"success": False, "message": "Failed to delete user"})
                
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/admin/inquiries/view/<inquiry_id>')
@login_required
def view_inquiry(inquiry_id):
    if not current_user.admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('dashboard'))
    
    inquiry = inquiries_collection.find_one({"_id": ObjectId(inquiry_id)})
    if not inquiry:
        flash('Inquiry not found', 'danger')
        return redirect(url_for('admin_inquiries'))

    user_data = users_collection.find_one({"_id": ObjectId(inquiry.get('user_id'))})
    
    return render_template('admin_view_inquiry.html', inquiry=inquiry, user=current_user, user_data=user_data)

@app.route('/admin/inquiries/update/<inquiry_id>', methods=['POST'])
@login_required
def update_inquiry(inquiry_id):
    if not current_user.admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('dashboard'))
    
    status = request.form.get('status')
    if not status:
        flash('Status is required', 'danger')
        return redirect(url_for('admin_inquiries'))
    
    try:
        # Find the inquiry
        inquiry = inquiries_collection.find_one({"_id": ObjectId(inquiry_id)})
        if not inquiry:
            flash('Inquiry not found', 'danger')
            return redirect(url_for('admin_inquiries'))
        
        # Update the inquiry status
        result = inquiries_collection.update_one(
            {"_id": ObjectId(inquiry_id)}, 
            {"$set": {
                "status": status,
                "updated_at": datetime.now(),
                "updated_by": current_user.id
            }}
        )
        
        # If the inquiry is approved, create a booking
        if status == "approved":
            # Get user details
            user_data = users_collection.find_one({"_id": ObjectId(inquiry.get('user_id'))})
            user_name = f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}" if user_data else "Unknown"
            
            # Create a booking entry
            booking_data = {
                "user_id": inquiry.get('user_id'),
                "customer_name": user_name,
                "car_id": inquiry.get('car_id'),
                "car_name": inquiry.get('car_name'),
                "start_date": inquiry.get('start_date'),
                "end_date": inquiry.get('end_date'),
                "days": inquiry.get('days', 0),
                "price_per_day": inquiry.get('price_per_day', 0),
                "total_price": inquiry.get('total_price', 0),
                "pickup_location": inquiry.get('pickup_location', ''),
                "return_location": inquiry.get('return_location', ''),
                "inquiry_id": ObjectId(inquiry_id),
                "status": "upcoming",  # Initial status is upcoming
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "created_by": current_user.id
            }
            
            # Insert the booking
            booking_result = bookings_collection.insert_one(booking_data)
            
            if booking_result.inserted_id:
                # Update the inquiry with the booking ID for reference
                inquiries_collection.update_one(
                    {"_id": ObjectId(inquiry_id)},
                    {"$set": {"booking_id": booking_result.inserted_id}}
                )
                
                # Update car status to reflect upcoming booking
                cars_collection.update_one(
                    {"_id": inquiry.get('car_id')},
                    {"$set": {"upcoming_booking": True}}
                )
                
                flash('Inquiry approved and booking created successfully!', 'success')
            else:
                flash('Inquiry status updated, but booking creation failed.', 'warning')
        
        elif status == "rejected":
            flash('Inquiry rejected.', 'info')
        else:
            flash('Inquiry status updated.', 'info')
        
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')
    
    return redirect(url_for('admin_inquiries'))

@app.route('/admin/bookings')
@login_required
def admin_bookings():
    if not current_user.admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('dashboard'))
    
    # Current date for calculations
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_date = today.date()
    tomorrow = today + timedelta(days=1)
    in_two_days = today + timedelta(days=2)
    
    # Helper function to parse date safely
    def parse_date(date_str):
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            try:
                return datetime.strptime(date_str, '%d/%m/%Y')
            except ValueError:
                return None
    
    # Fetch all bookings efficiently with a single query and sort
    pipeline = [
        {"$match": {"status": {"$in": ["upcoming", "active", "completed", "cancelled"]}}},
        {"$sort": {"created_at": -1}}
    ]
    all_bookings = list(bookings_collection.aggregate(pipeline))
    
    # Initialize categorized lists
    active_bookings = []
    upcoming_bookings = []
    ending_soon = []
    pickups_today = []
    returns_today = []
    completed_bookings = []
    monthly_revenue = 0
    
    # Current month range for revenue calculation
    month_start = today.replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    
    # Process all bookings in a single loop
    for booking in all_bookings:
        # Process based on status
        status = booking.get('status')
        
        # Parse dates once
        start_date = parse_date(booking.get('start_date'))
        end_date = parse_date(booking.get('end_date'))
        
        if status == 'active':
            # Calculate days left
            if end_date:
                days_left = max(0, (end_date.date() - today_date).days)
                booking['days_left'] = days_left
                
                # Check if ending soon (within 2 days)
                if days_left <= 2:
                    booking['ends_in'] = "Today" if days_left == 0 else "Tomorrow" if days_left == 1 else f"{days_left} days"
                    ending_soon.append(booking)
                
                # Check if returning today
                if end_date.date() == today_date:
                    returns_today.append(booking)
                
            active_bookings.append(booking)
            
        elif status == 'upcoming':
            if start_date:
                days_until = max(0, (start_date.date() - today_date).days)
                booking['starts_in'] = "Today" if days_until == 0 else "Tomorrow" if days_until == 1 else f"{days_until} days"
                
                # Check if pickup is today
                if start_date.date() == today_date:
                    pickups_today.append(booking)
                
            upcoming_bookings.append(booking)
            
        elif status == 'completed':
            completed_at = booking.get('completed_at')
            if isinstance(completed_at, datetime):
                if month_start <= completed_at < next_month:
                    monthly_revenue += booking.get('total_price', 0)
            completed_bookings.append(booking)
    
    # Sort completed bookings by completion date
    completed_bookings.sort(key=lambda x: x.get('completed_at', datetime.min), reverse=True)
    
    return render_template(
        'admin_bookings.html',
        user=current_user,
        bookings=all_bookings,
        active_bookings=active_bookings,
        upcoming_bookings=upcoming_bookings,
        ending_soon=ending_soon,
        completed_bookings=completed_bookings,
        pickups_today=pickups_today,
        returns_today=returns_today,
        monthly_revenue=monthly_revenue,
        active_page='bookings'
    )

@app.route('/admin/bookings/details/<booking_id>')
@login_required
def booking_details_api(booking_id):
    if not current_user.admin:
        return jsonify({"error": "Access denied"}), 403
    
    try:
        booking = bookings_collection.find_one({"_id": ObjectId(booking_id)})
        if not booking:
            return jsonify({"error": "Booking not found"}), 404
        
        # Convert ObjectId to string for JSON serialization
        booking['_id'] = str(booking['_id'])
        
        return jsonify(booking)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/admin/bookings/update-status', methods=['POST'])
@login_required
def update_booking_status():
    if not current_user.admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('dashboard'))
    
    booking_id = request.form.get('booking_id')
    status = request.form.get('status')
    notes = request.form.get('notes', '')
    
    if not booking_id or not status:
        flash('Booking ID and status are required', 'danger')
        return redirect(url_for('admin_bookings'))
    
    try:
        # Get the booking
        booking = bookings_collection.find_one({"_id": ObjectId(booking_id)})
        if not booking:
            flash('Booking not found', 'danger')
            return redirect(url_for('admin_bookings'))
        
        # Update fields based on status
        update_data = {
            "status": status,
            "updated_at": datetime.now(),
            "status_history": booking.get('status_history', []) + [{
                "status": status,
                "changed_at": datetime.now(),
                "notes": notes,
                "changed_by": current_user.id
            }]
        }
        
        # Add special fields based on status
        if status == "completed":
            update_data["completed_at"] = datetime.now()
            
            # Update car status to available
            cars_collection.update_one(
                {"_id": booking.get('car_id')},
                {"$set": {"booked": False, "status": "Available"}}
            )
        elif status == "active":
            # Update car status to booked
            cars_collection.update_one(
                {"_id": booking.get('car_id')},
                {"$set": {"booked": True, "status": "Booked"}}
            )
        
        # Update booking
        result = bookings_collection.update_one(
            {"_id": ObjectId(booking_id)},
            {"$set": update_data}
        )
        
        if result.modified_count:
            flash(f'Booking status updated to {status}', 'success')
        else:
            flash('No changes were made to the booking', 'info')
    
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')
    
    return redirect(url_for('admin_bookings'))

@app.route('/admin/bookings/extend', methods=['POST'])
@login_required
def extend_booking():
    if not current_user.admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('dashboard'))
    
    booking_id = request.form.get('booking_id')
    new_end_date = request.form.get('new_end_date')
    additional_amount = request.form.get('additional_amount')
    reason = request.form.get('reason', '')
    
    if not booking_id or not new_end_date or not additional_amount:
        flash('All fields are required', 'danger')
        return redirect(url_for('admin_bookings'))
    
    try:
        # Get the booking
        booking = bookings_collection.find_one({"_id": ObjectId(booking_id)})
        if not booking:
            flash('Booking not found', 'danger')
            return redirect(url_for('admin_bookings'))
        
        # Calculate new total price
        total_price = booking.get('total_price', 0) + float(additional_amount)
        
        # Update booking
        update_data = {
            "end_date": new_end_date,
            "total_price": total_price,
            "updated_at": datetime.now(),
            "extension_history": booking.get('extension_history', []) + [{
                "original_end_date": booking.get('end_date'),
                "new_end_date": new_end_date,
                "additional_amount": float(additional_amount),
                "reason": reason,
                "extended_at": datetime.now(),
                "extended_by": current_user.id
            }]
        }
        
        result = bookings_collection.update_one(
            {"_id": ObjectId(booking_id)},
            {"$set": update_data}
        )
        
        if result.modified_count:
            flash('Booking extended successfully', 'success')
        else:
            flash('No changes were made to the booking', 'info')
    
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')
    
    return redirect(url_for('admin_bookings'))

@app.route('/admin/bookings/view/<booking_id>')
@login_required
def view_booking(booking_id):
    if not current_user.admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        booking = bookings_collection.find_one({"_id": ObjectId(booking_id)})
        if not booking:
            flash('Booking not found', 'danger')
            return redirect(url_for('admin_bookings'))
        
        # Get car details
        car = None
        if booking.get('car_id'):
            car = cars_collection.find_one({"_id": booking.get('car_id')})
        
        # Get customer details
        customer = None
        if booking.get('user_id'):
            customer = users_collection.find_one({"_id": ObjectId(booking.get('user_id'))})
        
        return render_template(
            'admin_view_booking.html',
            booking=booking,
            car=car,
            customer=customer,
            user=current_user
        )
    
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')
        return redirect(url_for('admin_bookings'))

@app.route('/admin/bookings/invoice/<booking_id>')
@login_required
def generate_booking_invoice(booking_id):
    if not current_user.admin:
        flash('Access denied. Admin privileges required.', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        booking = bookings_collection.find_one({"_id": ObjectId(booking_id)})
        if not booking:
            flash('Booking not found', 'danger')
            return redirect(url_for('admin_bookings'))
        
        # Get car details
        car = None
        if booking.get('car_id'):
            car = cars_collection.find_one({"_id": booking.get('car_id')})
        
        # Get customer details
        customer = None
        if booking.get('user_id'):
            customer = users_collection.find_one({"_id": ObjectId(booking.get('user_id'))})
        
        return render_template(
            'admin_booking_invoice.html',
            booking=booking,
            car=car,
            customer=customer,
            user=current_user,
            invoice_date=datetime.now().strftime('%Y-%m-%d'),
            invoice_number=f"INV-{booking_id[-6:]}-{datetime.now().strftime('%Y%m%d')}"
        )
    
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')
        return redirect(url_for('admin_bookings'))

@app.route('/tos',methods=['GET'])
def tos():
    return render_template('tos.html')

@app.route('/privacypolicy',methods=['GET'])
def privacypolicy():
    return render_template('privacy.html')

def background_task():
    """
    Updates the status of cars and bookings in the database.
    - Upcoming bookings with start dates that have passed are marked as active
    - Active bookings with end dates that have passed are marked as completed
    - Car statuses are updated accordingly
    """
    print("Background task started")
    while True:
        try:
            # Get current date in YYYY-MM-DD format
            today = datetime.now().strftime('%Y-%m-%d')
            
            # Check for upcoming bookings that should be active
            upcoming_bookings = bookings_collection.find({"status": "upcoming", "start_date": {"$lte": today}})
            for booking in upcoming_bookings:
                bookings_collection.update_one(
                    {"_id": booking["_id"]}, 
                    {"$set": {
                        "status": "active",
                        "updated_at": datetime.now(),
                        "status_history": booking.get('status_history', []) + [{
                            "status": "active",
                            "changed_at": datetime.now(),
                            "notes": "Automatically updated by system",
                            "changed_by": "system"
                        }]
                    }}
                )
                # Update car status
                cars_collection.update_one(
                    {"_id": booking["car_id"]}, 
                    {"$set": {"status": "Booked", "booked": True}}
                )
                print(f"Booking {booking['_id']} updated to active")
            
            # Check for active bookings that should be completed
            active_bookings = bookings_collection.find({"status": "active", "end_date": {"$lte": today}})
            for booking in active_bookings:
                bookings_collection.update_one(
                    {"_id": booking["_id"]}, 
                    {"$set": {
                        "status": "completed",
                        "updated_at": datetime.now(),
                        "completed_at": datetime.now(),
                        "status_history": booking.get('status_history', []) + [{
                            "status": "completed",
                            "changed_at": datetime.now(),
                            "notes": "Automatically updated by system",
                            "changed_by": "system"
                        }]
                    }}
                )
                # Update car status
                cars_collection.update_one(
                    {"_id": booking["car_id"]}, 
                    {"$set": {"status": "Available", "booked": False}}
                )
                print(f"Booking {booking['_id']} updated to completed")
            
            print(f"Background task completed at {datetime.now()}")
        except Exception as e:
            print(f"Error in background task: {e}")
        
        # Sleep for 12 hours
        time.sleep(43200)

@app.route('/api/v1/manage/site', methods=['POST'])
def manage_site():
    """
    Endpoint to manage the site status.
    It will change the WEBSITE_STATUS global variable to the value provided in the request.
    """
    if request.method == 'POST':
        data = request.get_json()
        if not data or 'auth_key' not in data or 'status' not in data:
            return jsonify({"error": "Invalid request"}), 400
        auth_key = data['auth_key']
        AUTH_KEY = os.getenv('AUTH_KEY', "FounDevStudiio@AlexaCars")
        if auth_key != AUTH_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        
        status = data['status']
        if status not in ['ONLINE', 'OFFLINE', 'MAINTENANCE']:
            return jsonify({"error": "Invalid status value"}), 400
        
        if status == "MAINTENANCE":
            global DEPLOYMENT_LINK
            if DEPLOYMENT_LINK:
                try:
                    response = requests.get(DEPLOYMENT_LINK)
                    if response.status_code == 200:
                        return jsonify({"message": "Website has been deployed successfully"}), 200
                    else:
                        return jsonify({"error": "Deployment link is not reachable"}), 500
                except requests.RequestException as e:
                    return jsonify({"error": f"Error reaching deployment link: {str(e)}"}), 500

        global WEBSITE_STATUS
        WEBSITE_STATUS = status
        return jsonify({"message": f"Website status updated to {status}"}), 200
    
    return jsonify({"error": "Method not allowed"}), 405

def deploy():
    bg_thread = threading.Thread(target=background_task)
    bg_thread.daemon = True
    bg_thread.start()

    app.run(debug=True, host='0.0.0.0', port=80)

if __name__ == "__main__":
    deploy()
