from datetime import datetime
from geopy.distance import geodesic

def calculate_distance(user_coords, hospital_coords):
    """Tính khoảng cách (km) giữa 2 tọa độ."""
    return geodesic(user_coords, hospital_coords).km

def calculate_ai_score(distance, user, radius_km):
    """
    Tính điểm phù hợp (0-1) cho người dùng dựa trên nhiều yếu tố.
    - 40% từ khoảng cách
    - 30% từ lịch sử hiến máu
    - 30% từ thời gian phù hợp
    """
    # 1. Điểm khoảng cách (càng gần điểm càng cao)
    distance_score = max(0, 1 - (distance / radius_km))
    
    is_eligible = True
    recovery_days_left = 0
    
    # 2. Điểm lịch sử hiến máu (lần hiến cuối càng xa càng tốt)
    if user.last_donation:
        required_days = 84
        try:
            completed_records = [r for r in user.donation_records if r.status == 'completed']
            if completed_records:
                last_record = max(completed_records, key=lambda r: r.donation_date)
                if last_record.donation_type and ('Tiểu cầu' in last_record.donation_type or 'Huyết tương' in last_record.donation_type):
                    required_days = 14
        except Exception:
            pass

        days_since_donation = (datetime.now().date() - user.last_donation).days
        # Cần đợi đủ số ngày tương ứng
        if days_since_donation < required_days:
            history_score = 0
            is_eligible = False
            recovery_days_left = required_days - days_since_donation
        else:
            # Điểm tăng dần đến 180 ngày
            history_score = min(1.0, (days_since_donation - required_days) / (180 - required_days))
    else:
        # Chưa hiến bao giờ = hoàn toàn sẵn sàng
        history_score = 1.0
    
    # 3. Điểm thời gian (giờ hành chính tốt hơn)
    current_hour = datetime.now().hour
    time_score = 1.0 if 8 <= current_hour < 20 else 0.5 # Từ 8h sáng đến 8h tối
    
    # Điểm tổng hợp cuối cùng
    final_score = (
        distance_score * 0.4 +
        history_score * 0.3 +
        time_score * 0.3
    )
    if not is_eligible:
        final_score = -1.0 # Force negative score to push to bottom

    return final_score, is_eligible, recovery_days_left

def filter_nearby_users(hospital, users, radius_km=10):
    """
    Lọc danh sách người dùng dựa trên khoảng cách tới bệnh viện và tính điểm AI.
    """
    hospital_coords = (hospital.lat, hospital.lng)
    results = []
    
    for user in users:
        user_coords = (user.lat, user.lng)
        distance = calculate_distance(user_coords, hospital_coords)
        
        if distance <= radius_km:
            score, is_eligible, recovery_days_left = calculate_ai_score(distance, user, radius_km)
            results.append({
                'user': user,
                'distance': round(distance, 2),
                'ai_score': round(max(0, score), 3),
                'is_eligible': is_eligible,
                'recovery_days_left': recovery_days_left
            })
    
    # Sắp xếp kết quả: is_eligible ưu tiên lên trước (True > False), sau đó đến điểm AI giảm dần
    results.sort(key=lambda x: (x['is_eligible'], x['ai_score']), reverse=True)
    
    return results

