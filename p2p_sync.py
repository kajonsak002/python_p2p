import socket  # ใช้สำหรับการสื่อสารผ่านเครือข่าย
import threading  # ใช้สำหรับการทำงานแบบหลาย thread
import json  # ใช้สำหรับการเข้าและถอดรหัสข้อมูล JSON
import sys  # ใช้สำหรับการรับ argument จาก command line
import os  # ใช้สำหรับการจัดการไฟล์และตรวจสอบการมีอยู่ของไฟล์
import secrets  # ใช้สำหรับการสร้างข้อมูลที่ปลอดภัยทางคริปโตกราฟี

class Node:
    def __init__(self, host, port):
        self.host = host  # เก็บ IP address ของ Node
        self.port = port  # เก็บหมายเลขพอร์ตของ Node
        self.peers = []  # รายการ socket ของ peer ที่เชื่อมต่อ
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # สร้าง socket สำหรับการสื่อสาร TCP/IP
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # ตั้งค่า socket ให้สามารถใช้ address ซ้ำได้
        self.transactions = []  # รายการธุรกรรมทั้งหมด
        self.transaction_file = f"transactions_{port}.json"  # ชื่อไฟล์สำหรับบันทึกธุรกรรม (แยกตามพอร์ต)
        self.wallet_address = self.generate_wallet_address()  # สร้างและเก็บ wallet address

    def generate_wallet_address(self):
        # สร้าง wallet address แบบสุ่มด้วย secrets.token_hex
        # ใช้ 20 ไบต์ (40 ตัวอักษรเลขฐาน 16) และเพิ่ม '0x' นำหน้า
        return '0x' + secrets.token_hex(20)

    def start(self):
        # ผูกและเริ่มฟังการเชื่อมต่อที่ socket
        self.socket.bind((self.host, self.port))
        self.socket.listen(1)  # รับการเชื่อมต่อได้สูงสุด 1 ครั้งก่อนปฏิเสธ
        print(f"Node listening on {self.host}:{self.port}")
        print(f"Your wallet address is: {self.wallet_address}")

        self.load_transactions()  # โหลดธุรกรรมจากไฟล์ (ถ้ามี)

        # สร้างและเริ่ม thread สำหรับรับการเชื่อมต่อใหม่
        accept_thread = threading.Thread(target=self.accept_connections)
        accept_thread.start()

    def accept_connections(self):
        while True:
            # วนลูปรอรับการเชื่อมต่อใหม่ตลอดเวลา
            client_socket, address = self.socket.accept()  # รอรับการเชื่อมต่อ (blocking)
            print(f"New connection from {address}")

            # สร้าง thread ใหม่สำหรับจัดการแต่ละการเชื่อมต่อ
            client_thread = threading.Thread(target=self.handle_client, args=(client_socket,))
            client_thread.start()

    def handle_client(self, client_socket):
        while True:
            try:
                # รับข้อมูลจาก client (สูงสุด 1024 ไบต์)
                data = client_socket.recv(1024)
                if not data:
                    # ถ้าไม่มีข้อมูล แสดงว่าการเชื่อมต่อถูกปิด
                    break
                # แปลงข้อมูล JSON เป็น Python object
                message = json.loads(data.decode('utf-8'))
                
                # ส่งข้อความไปประมวลผล
                self.process_message(message, client_socket)

            except Exception as e:
                print(f"Error handling client: {e}")
                break

        client_socket.close()  # ปิดการเชื่อมต่อเมื่อจบการทำงาน

    def connect_to_peer(self, peer_host, peer_port):
        try:
            # สร้าง socket ใหม่สำหรับการเชื่อมต่อกับ peer
            peer_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            peer_socket.connect((peer_host, peer_port))  # เชื่อมต่อไปยัง peer
            self.peers.append(peer_socket)  # เพิ่ม socket ของ peer ลงในรายการ
            print(f"Connected to peer {peer_host}:{peer_port}")

            # ขอข้อมูล sync จาก peer ที่เพิ่งเชื่อมต่อ
            self.request_sync(peer_socket)

            # สร้าง thread ใหม่สำหรับจัดการการสื่อสารกับ peer
            peer_thread = threading.Thread(target=self.handle_client, args=(peer_socket,))
            peer_thread.start()

        except Exception as e:
            print(f"Error connecting to peer: {e}")

    def broadcast(self, message):
        # ส่งข้อความไปยังทุก peer ที่เชื่อมต่ออยู่
        for peer_socket in self.peers:
            try:
                # แปลงข้อความเป็น JSON และส่งไปยัง peer
                peer_socket.send(json.dumps(message).encode('utf-8'))
            except Exception as e:
                print(f"Error broadcasting to peer: {e}")
                self.peers.remove(peer_socket)  # ลบ peer ที่มีปัญหาออกจากรายการ

    def process_message(self, message, client_socket):
        # ประมวลผลข้อความตามประเภท
        if message['type'] == 'transaction':
            print(f"Received transaction: {message['data']}")
            self.add_transaction(message['data'])
        elif message['type'] == 'sync_request':
            self.send_all_transactions(client_socket)
        elif message['type'] == 'sync_response':
            self.receive_sync_data(message['data'])
        else:
            print(f"Received unknown message type: {message}")

    def add_transaction(self, transaction):
        # เพิ่มธุรกรรมใหม่ถ้ายังไม่มีอยู่ในรายการ
        if transaction not in self.transactions:
            self.transactions.append(transaction)
            self.save_transactions()  # บันทึกธุรกรรมลงไฟล์
            print(f"Transaction added and saved: {transaction}")

    def create_transaction(self, recipient, amount):
        # สร้างธุรกรรมใหม่
        transaction = {
            'sender': self.wallet_address,
            'recipient': recipient,
            'amount': amount
        }
        self.add_transaction(transaction)  # เพิ่มธุรกรรมลงในรายการของตัวเอง
        self.broadcast({'type': 'transaction', 'data': transaction})  # ส่งธุรกรรมไปยังทุก peer

    def save_transactions(self):
        # บันทึกธุรกรรมทั้งหมดลงในไฟล์ JSON
        with open(self.transaction_file, 'w') as f:
            json.dump(self.transactions, f)

    def load_transactions(self):
        # โหลดธุรกรรมจากไฟล์ (ถ้ามี)
        if os.path.exists(self.transaction_file):
            with open(self.transaction_file, 'r') as f:
                self.transactions = json.load(f)
            print(f"Loaded {len(self.transactions)} transactions from file.")

    def request_sync(self, peer_socket):
        # ส่งคำขอ sync ไปยัง peer
        sync_request = json.dumps({"type": "sync_request"}).encode('utf-8')
        peer_socket.send(sync_request)

    def send_all_transactions(self, client_socket):
        # ส่งธุรกรรมทั้งหมดไปยัง client ที่ขอ sync
        sync_data = json.dumps({
            "type": "sync_response",
            "data": self.transactions
        }).encode('utf-8')
        client_socket.send(sync_data)

    def receive_sync_data(self, sync_transactions):
        # รับข้อมูล sync และเพิ่มธุรกรรมที่ยังไม่มี
        for tx in sync_transactions:
            self.add_transaction(tx)
        print(f"Synchronized {len(sync_transactions)} transactions.")

if __name__ == "__main__":
    # ตรวจสอบว่ามีการระบุพอร์ตที่ถูกต้องหรือไม่
    if len(sys.argv) != 2:
        print("Usage: python script.py <port>")
        sys.exit(1)
    
    port = int(sys.argv[1])  # แปลงพอร์ตจากสตริงเป็นตัวเลข
    node = Node("0.0.0.0", port)  # สร้าง Node instance (0.0.0.0 หมายถึงรับการเชื่อมต่อจากทุก interface)
    node.start()  # เริ่มการทำงานของ Node
    
    while True:
        # แสดงเมนูและรับคำสั่งจากผู้ใช้
        print("\n1. Connect to a peer")
        print("2. Create a transaction")
        print("3. View all transactions")
        print("4. View my wallet address")
        print("5. Exit")
        choice = input("Enter your choice: ")
        
        if choice == '1':
            # เชื่อมต่อกับ peer ใหม่
            peer_host = input("Enter peer host to connect: ")
            peer_port = int(input("Enter peer port to connect: "))
            node.connect_to_peer(peer_host, peer_port)
        elif choice == '2':
            # สร้างธุรกรรมใหม่
            recipient = input("Enter recipient wallet address: ")
            amount = float(input("Enter amount: "))
            node.create_transaction(recipient, amount)
        elif choice == '3':
            # แสดงธุรกรรมทั้งหมด
            print("All transactions:")
            for tx in node.transactions:
                print(tx)
        elif choice == '4':
            # แสดง wallet address ของตัวเอง
            print(f"Your wallet address is: {node.wallet_address}")
        elif choice == '5':
            # ออกจากโปรแกรม
            break
        else:
            print("Invalid choice. Please try again.")

    print("Exiting...")  # แสดงข้อความเมื่อออกจากโปรแกรม