from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q, Max
from stocks.models import PrecisionScanCandidate

@login_required
def sector_rotation_dashboard(request):
    market = request.GET.get('market', 'SET')
    
    # Get latest scan run for this market
    latest_run = PrecisionScanCandidate.objects.filter(market=market).aggregate(Max('scan_run'))['scan_run__max']
    
    sectors_data = []
    last_updated = None
    
    if latest_run:
        last_updated = latest_run
        
        # Get all stocks from the latest run, excluding unknown sectors
        qs = PrecisionScanCandidate.objects.filter(
            scan_run=latest_run,
            market=market
        ).exclude(sector__in=['', 'Unknown', 'N/A', 'None'])
        
        # Get unique sectors
        sector_names = set(qs.values_list('sector', flat=True))
        
        for s_name in sector_names:
            sec_qs = qs.filter(sector=s_name)
            
            total_stocks = sec_qs.count()
            if total_stocks == 0:
                continue
                
            stage2_count = sec_qs.filter(stage2=True).count()
            stage2_ratio = (stage2_count / total_stocks) * 100
            
            avg_tech = sec_qs.aggregate(Avg('technical_score'))['technical_score__avg'] or 0
            avg_rs = sec_qs.aggregate(Avg('rs_rating'))['rs_rating__avg'] or 0
            
            top_stocks = sec_qs.order_by('-technical_score', '-rs_rating')[:5]
            
            sectors_data.append({
                'name': s_name,
                'total_stocks': total_stocks,
                'stage2_count': stage2_count,
                'stage2_ratio': round(stage2_ratio, 1),
                'avg_tech': round(avg_tech, 1),
                'avg_rs': round(avg_rs, 1),
                'top_stocks': top_stocks
            })
            
        # Sort by Stage 2 Ratio DESC, then Average Tech Score DESC
        sectors_data.sort(key=lambda x: (x['stage2_ratio'], x['avg_tech']), reverse=True)
        
    context = {
        'market': market,
        'sectors_data': sectors_data,
        'last_updated': last_updated
    }
    
    return render(request, 'stocks/sector_rotation.html', context)
