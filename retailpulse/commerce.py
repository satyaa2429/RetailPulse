"""Integer-paise checkout pricing and locally generated UPI QR codes."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlencode
import re


def rounded(value):
    return int(Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def decimal(value, label, maximum):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(label+' must be a number.')
    if not number.is_finite() or number < 0 or number > maximum:
        raise ValueError(label+' is outside its allowed range.')
    return number


def settings(payload, products):
    upi = payload.get('upi_id',''); gstin = payload.get('gstin','')
    if not isinstance(upi,str) or not isinstance(gstin,str): raise ValueError('UPI ID and GSTIN must be text.')
    upi=upi.strip();gstin=gstin.strip().upper()
    mode = payload.get('gst_mode','off')
    if upi and not re.fullmatch(r'[A-Za-z0-9._-]{2,256}@[A-Za-z0-9.-]{2,64}',upi):
        raise ValueError('Enter a valid UPI ID, such as shop@bank.')
    if mode not in ('off','inclusive','exclusive'):
        raise ValueError('Select a valid GST price mode.')
    if mode!='off' and not re.fullmatch(r'[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]',gstin):
        raise ValueError('Enter your GSTIN before enabling GST. Registration is not verified by this app.')
    rates = payload.get('rates',{})
    if not isinstance(rates,dict): raise ValueError('GST rates must be an item map.')
    clean = {}
    for sku, value in rates.items():
        if sku not in products: raise ValueError('Unknown product in GST settings.')
        clean[sku] = str(decimal(value,'GST rate',100))
    return {'upi_id':upi,'gstin':gstin,'gst_mode':mode,'rates':clean}


def price(lines, config, options):
    if not isinstance(options,dict): raise ValueError('Billing options must be an object.')
    kind=options.get('discount_type','amount')
    if kind not in ('amount','percent'): raise ValueError('Choose an amount or percentage discount.')
    subtotal=sum(line['quantity']*line['unit_price_minor'] for line in lines)
    value=decimal(options.get('discount_value',0),'Discount',100 if kind=='percent' else Decimal(subtotal)/100)
    discount=rounded(Decimal(subtotal)*value/100) if kind=='percent' else rounded(value*100)
    if discount>=subtotal: raise ValueError('Discount must leave a positive bill total.')
    supply=options.get('supply_type','local')
    if supply not in ('local','interstate'): raise ValueError('Choose local or interstate supply.')
    mode=config.get('gst_mode','off')
    result=[]; allocated=0; cumulative=0
    for line in lines:
        gross=line['quantity']*line['unit_price_minor']; cumulative+=gross
        target=discount*cumulative//subtotal
        reduction=target-allocated; allocated=target
        base=gross-reduction
        if mode!='off' and line['sku'] not in config.get('rates',{}):
            raise ValueError('Set a GST rate (including 0 for exempt items) for '+line['sku']+'.')
        rate=decimal(config.get('rates',{}).get(line['sku'],0),'GST rate',100) if mode!='off' else Decimal(0)
        taxable=rounded(Decimal(base)*100/(100+rate)) if mode=='inclusive' else base
        tax=base-taxable if mode=='inclusive' else rounded(Decimal(taxable)*rate/100)
        cgst=tax//2 if supply=='local' else 0
        result.append({**line,'gross_minor':gross,'discount_minor':reduction,'taxable_minor':taxable,
            'gst_rate':str(rate),'cgst_minor':cgst,'sgst_minor':tax-cgst if supply=='local' else 0,
            'igst_minor':tax if supply=='interstate' else 0,'tax_minor':tax,'total_minor':taxable+tax})
    return {'subtotal_minor':subtotal,'discount_minor':discount,'taxable_minor':sum(l['taxable_minor'] for l in result),
        'tax_minor':sum(l['tax_minor'] for l in result),'total_minor':sum(l['total_minor'] for l in result),
        'gst_mode':mode,'gstin':config.get('gstin','') if mode!='off' else '',
        'supply_type':supply,'lines':result}


def payment_uri(upi, name, amount, reference):
    return 'upi://pay?'+urlencode({'pa':upi,'pn':name,'am':f'{amount/100:.2f}','cu':'INR','tr':reference,'tn':'Satya Shop purchase'})


def qr_svg(uri):
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics import renderSVG
    qr=QrCodeWidget(uri,barLevel='M'); bounds=qr.getBounds(); size=320
    width=bounds[2]-bounds[0]; height=bounds[3]-bounds[1]
    drawing=Drawing(size,size,transform=[size/width,0,0,size/height,0,0]); drawing.add(qr)
    return renderSVG.drawToString(drawing).encode('utf-8')
