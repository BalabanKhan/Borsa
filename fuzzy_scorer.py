import math

def sigmoid_score(value, center, k=1.0, max_score=100.0, reverse=False):
    """
    S-Eğrisi (Sigmoid) kullanarak yumuşak puanlama yapar.
    :param value: Değerlendirecek olan metrik (ör: ADX, RSI)
    :param center: Eğrinin orta noktası (50 puan alınacak yer)
    :param k: Eğimin keskinliği (pozitif). Ne kadar yüksekse o kadar keskin bir eşik olur.
    :param max_score: Maksimum puan
    :param reverse: Eğer True ise düşük değerler yüksek puan alır (ör: düşen RSI).
    """
    try:
        if reverse:
            score = max_score / (1 + math.exp(k * (value - center)))
        else:
            score = max_score / (1 + math.exp(-k * (value - center)))
        return score
    except OverflowError:
        return 0.0 if not reverse else max_score

def linear_score(value, min_val, max_val, max_score=100.0, reverse=False):
    """
    Doğrusal (Linear) puanlama yapar. min_val altı 0, max_val üstü max_score alır.
    :param value: Değerlendirilecek metrik
    :param min_val: Puanın sıfırlandığı alt sınır
    :param max_val: Puanın max_score olduğu üst sınır
    :param reverse: True ise min_val altı max_score, max_val üstü 0 alır.
    """
    if min_val == max_val:
        return max_score if value >= max_val else 0.0
        
    if reverse:
        if value <= min_val: return max_score
        if value >= max_val: return 0.0
        return max_score * (1.0 - (value - min_val) / (max_val - min_val))
    else:
        if value <= min_val: return 0.0
        if value >= max_val: return max_score
        return max_score * ((value - min_val) / (max_val - min_val))

def gaussian_score(value, center, width=10.0, max_score=100.0):
    """
    Çan eğrisi (Gaussian) kullanarak puanlama yapar.
    Özellikle hedeflenen belirli bir aralığa yakınlık istendiğinde (Örn: RSI 50 çevresi) kullanılır.
    :param value: Değer
    :param center: Zirve puanın alınacağı ideal nokta
    :param width: Eğrinin genişliği (varyansla ilişkili)
    """
    try:
        return max_score * math.exp(-0.5 * ((value - center) / width) ** 2)
    except OverflowError:
        return 0.0

def calculate_fuzzy_setup_score(components, weights):
    """
    Çeşitli fuzzy bileşenlerin puanlarını ağırlıklı ortalama ile birleştirip tek bir "Setup Score" (Kurulum Puanı) üretir.
    :param components: {'adx': 85.0, 'rsi': 60.0, ...} şeklinde bileşen puanları
    :param weights: {'adx': 0.4, 'rsi': 0.6, ...} şeklinde bileşen ağırlıkları. Toplamı 1.0 olmalı.
    """
    total_score = 0.0
    total_weight = 0.0
    
    for key, score in components.items():
        weight = weights.get(key, 0.0)
        total_score += score * weight
        total_weight += weight
        
    if total_weight == 0.0:
        return 0.0
        
    return total_score / total_weight

