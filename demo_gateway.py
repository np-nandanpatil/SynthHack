import os
import sys
import csv
import json
import random
import uuid
from datetime import datetime, timedelta

# Add the project root directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from src.utils.predictor import RealTimePredictor

app = Flask(__name__)
app.secret_key = os.urandom(24)  # For session management

# Initialize the fraud detection system
predictor = RealTimePredictor('models/fraud_detection_model.pkl', 'models/feature_engineer.pkl')

# In-memory storage for transactions and OTPs
transactions_db = {}
otps = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    """Payment gateway dashboard showing transaction history"""
    # In a real implementation, this would fetch from a database
    txn_data = []
    try:
        with open('data/processed_transactions.csv', 'r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                txn_data.append(row)
    except FileNotFoundError:
        pass
    
    return render_template('dashboard.html', transactions=txn_data)

# Ensure the CSV file exists with headers
def ensure_transaction_csv_exists():
    csv_path = 'data/processed_transactions.csv'
    if not os.path.exists(csv_path):
        with open(csv_path, 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([
                'Transaction_ID',
                'Timestamp',
                'Amount',
                'Sender_ID',
                'Receiver_ID',
                'Transaction_Type',
                'Merchant_Type',
                'Device_ID',
                'Location',
                'Is_Fraud',
                'Fraud_Type',
                'Fraud_Probability',
                'Status'
            ])

@app.route('/payment_methods')
def payment_methods():
    """Display available payment methods"""
    return render_template('payment_methods.html')

@app.route('/netbanking')
def netbanking():
    """Display netbanking options"""
    banks = [
        {"id": "sbi", "name": "State Bank of India"},
        {"id": "hdfc", "name": "HDFC Bank"},
        {"id": "icici", "name": "ICICI Bank"},
        {"id": "axis", "name": "Axis Bank"},
        {"id": "kotak", "name": "Kotak Mahindra Bank"},
        {"id": "pnb", "name": "Punjab National Bank"}
    ]
    return render_template('netbanking.html', banks=banks)

@app.route('/wallets')
def wallets():
    """Display wallet options"""
    wallets = [
        {"id": "paytm", "name": "Paytm"},
        {"id": "phonepe", "name": "PhonePe"},
        {"id": "gpay", "name": "Google Pay"},
        {"id": "amazonpay", "name": "Amazon Pay"},
        {"id": "mobikwik", "name": "MobiKwik"}
    ]
    return render_template('wallets.html', wallets=wallets)

@app.route('/process_transaction', methods=['POST'])
def process_transaction():
    transaction_data = request.json
    
    # Generate a unique transaction ID if not provided
    if 'Transaction_ID' not in transaction_data:
        transaction_data['Transaction_ID'] = f"TXN_{uuid.uuid4().hex[:10]}"
    
    # Add Receiver_ID if not present
    if 'Receiver_ID' not in transaction_data:
        transaction_data['Receiver_ID'] = 'Merchant_' + str(hash(transaction_data.get('Merchant_Type', '')) % 10000)
    
    # Step 1: Fraud detection
    result = predictor.predict_transaction(transaction_data)
    
    # If fraudulent, block immediately
    if result['is_fraud']:
        log_transaction(transaction_data, result, "BLOCKED")
        return jsonify({
            'status': 'blocked',
            'reason': result['fraud_type'],
            'confidence': result['fraud_probability']
        }), 403
    
    # Step 2: For legitimate transactions, proceed with payment flow
    txn_id = transaction_data['Transaction_ID']
    
    # Store transaction for later verification
    transactions_db[txn_id] = {
        'data': transaction_data,
        'result': result,
        'status': 'PENDING'
    }
    
    # Generate OTP for authentication (simulate bank OTP)
    otp = str(random.randint(100000, 999999))
    otps[txn_id] = otp
    
    # In real implementation, OTP would be sent via SMS/email
    
    return jsonify({
        'status': 'pending_verification',
        'transaction_id': txn_id,
        'redirect_url': f"/verify_otp/{txn_id}",
        'confidence': result['fraud_probability']
    }), 200

@app.route('/verify_otp/<txn_id>', methods=['GET', 'POST'])
def verify_otp(txn_id):
    """OTP verification page"""
    if request.method == 'POST':
        user_otp = request.form.get('otp')
        
        # Verify OTP
        if txn_id in otps and user_otp == otps[txn_id]:
            # OTP verified, complete transaction
            transaction = transactions_db.get(txn_id)
            if transaction:
                # Update status
                transaction['status'] = 'COMPLETED'
                log_transaction(transaction['data'], transaction['result'], "COMPLETED")
                
                # Clean up
                del otps[txn_id]
                
                return render_template('success.html', transaction=transaction)
        
        # Invalid OTP
        return render_template('verify_otp.html', txn_id=txn_id, error="Invalid OTP. Please try again.")
    
    # GET request - show OTP form
    return render_template('verify_otp.html', txn_id=txn_id)

@app.route('/payment_status/<txn_id>')
def payment_status(txn_id):
    """Check payment status"""
    transaction = transactions_db.get(txn_id)
    if not transaction:
        return jsonify({'status': 'not_found'}), 404
    
    return jsonify({
        'status': transaction['status'],
        'transaction_id': txn_id,
        'amount': transaction['data'].get('Amount'),
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/transactions', methods=['GET'])
def api_transactions():
    """API endpoint for transactions data"""
    txn_data = []
    try:
        with open('data/processed_transactions.csv', 'r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                txn_data.append(row)
    except FileNotFoundError:
        pass
    
    return jsonify(txn_data)

@app.route('/api/fraud_stats', methods=['GET'])
def api_fraud_stats():
    """API endpoint for fraud statistics"""
    try:
        with open('data/processed_transactions.csv', 'r') as file:
            reader = csv.DictReader(file)
            rows = list(reader)
            
            total = len(rows)
            fraud = sum(1 for r in rows if r['Is_Fraud'] == 'True')
            fraud_types = {}
            
            for row in rows:
                if row['Is_Fraud'] == 'True' and row['Fraud_Type']:
                    fraud_types[row['Fraud_Type']] = fraud_types.get(row['Fraud_Type'], 0) + 1
            
            return jsonify({
                'total_transactions': total,
                'fraud_count': fraud,
                'fraud_percentage': round(fraud/total*100, 2) if total > 0 else 0,
                'fraud_types': fraud_types
            })
    except FileNotFoundError:
        return jsonify({
            'total_transactions': 0,
            'fraud_count': 0,
            'fraud_percentage': 0,
            'fraud_types': {}
        })

def log_transaction(transaction_data, result, status):
    """Log transaction to CSV file"""
    # Ensure CSV file exists
    ensure_transaction_csv_exists()
    
    # Append transaction to CSV
    with open('data/processed_transactions.csv', mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([
            transaction_data.get('Transaction_ID', 'Unknown'),
            transaction_data.get('Timestamp', datetime.now().isoformat()),
            transaction_data.get('Amount', 0),
            transaction_data.get('Sender_ID', 'Unknown'),
            transaction_data.get('Receiver_ID', 'Unknown'),
            transaction_data.get('Transaction_Type', 'Unknown'),
            transaction_data.get('Merchant_Type', 'Unknown'),
            transaction_data.get('Device_ID', 'Unknown'),
            transaction_data.get('Location', '0.0, 0.0'),
            result['is_fraud'],
            result.get('fraud_type', ''),
            result['fraud_probability'],
            status
        ])

if __name__ == '__main__':
    # Ensure CSV exists before starting server
    ensure_transaction_csv_exists()
    app.run(debug=True) 