"""Itemized sales-receipt PDF from the immutable saved checkout."""
from io import BytesIO
from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

ASSETS = Path(__file__).parent / "assets"
pdfmetrics.registerFont(TTFont("RetailFont", str(ASSETS/"DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("RetailFontBold", str(ASSETS/"DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily("RetailFont",normal="RetailFont",bold="RetailFontBold",italic="RetailFont",boldItalic="RetailFontBold")

def receipt_pdf(bill, record_type="sale"):
    output = BytesIO()
    ink = colors.HexColor("#173e38")
    muted = colors.HexColor("#66756e")
    normal = ParagraphStyle("body",fontName="RetailFont",fontSize=10,leading=15,textColor=ink)
    title = ParagraphStyle("title",parent=normal,fontSize=24,leading=29,spaceAfter=10)
    small = ParagraphStyle("small",parent=normal,fontSize=8,leading=12,textColor=muted)
    right = ParagraphStyle("right",parent=normal,alignment=TA_RIGHT)
    is_return = record_type!="sale"
    label = "BILL CANCELLATION RECORD" if record_type=="cancellation" else "RETURN RECORD" if is_return else "SALES RECEIPT"
    document = SimpleDocTemplate(output,pagesize=A4,rightMargin=42,leftMargin=42,topMargin=42,bottomMargin=42,title="RetailPulse "+label.lower(),author=bill["shop_name"])
    amount = lambda v: f"{bill['currency']} {v/100:,.2f}"
    story = [Paragraph(escape(bill["shop_name"]),title),Paragraph(label,small),Spacer(1,16)]
    if bill["source"] == "demo":
        story += [Paragraph("DEMO TRANSACTION - SAMPLE BILL",ParagraphStyle("demo",parent=normal,textColor=colors.HexColor("#a15a20"))),Spacer(1,12)]
    fields = [("Return ID",bill["return_id"]),("Original bill ID",bill["bill_id"])] if is_return else [("Bill ID",bill["bill_id"])]
    fields += [("Issued (UTC)",bill["created_at"][:19].replace("T"," ")),("Business date",bill["business_date"]),("Customer",bill["customer_name"] or "Walk-in customer")]
    if is_return: fields += [("Reason",bill["reason"]),("Added back to stock","Yes" if bill["restock"] else "No")]
    elif bill.get("status","active")!="active": fields += [("Bill status",bill["status"].replace("_"," ").upper())]
    for label,value in fields:
        story.append(Paragraph(f"<b>{label}:</b> {escape(value)}",normal))
    if not is_return and bill.get("pricing",{}).get("gstin"):
        story.append(Paragraph("GSTIN: "+escape(bill["pricing"]["gstin"]),normal))
    if not is_return and bill.get("payment"):
        story.append(Paragraph("Payment: "+escape(bill["payment"]["method"])+" (receipt confirmed by cashier)",normal))
    story.append(Spacer(1,22))
    rows = [["Item", "Qty", "Unit price", "Amount"]]
    for line in bill["items"]:
        rows.append([Paragraph(escape(line["product_name"])+"<br/><font size='8' color='#66756e'>"+escape(line["sku"])+"</font>",normal),str(line["quantity"]),amount(line["unit_price_minor"]),amount(line["line_total_minor"])])
    table = Table(rows,colWidths=[205,40,105,161.27],repeatRows=1,hAlign="LEFT")
    table.setStyle(TableStyle([("FONTNAME",(0,0),(-1,-1),"RetailFont"),("BACKGROUND",(0,0),(-1,0),ink),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"RetailFontBold"),("FONTSIZE",(0,0),(-1,-1),9),("ALIGN",(1,0),(-1,-1),"RIGHT"),("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),12),("BOTTOMPADDING",(0,0),(-1,-1),12),("LINEBELOW",(0,1),(-1,-1),.4,colors.HexColor("#e5e9e2")),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f6f7f2")])]))
    if not is_return and bill.get("pricing"):
        pricing=bill["pricing"]
        story += [Spacer(1,12),Paragraph("Subtotal: "+amount(pricing["subtotal_minor"]),right),Paragraph("Discount: "+amount(pricing["discount_minor"]),right)]
        if pricing["gst_mode"]!="off":
            story += [Paragraph("Taxable value: "+amount(pricing["taxable_minor"]),right)]
            for line in pricing["lines"]:
                story.append(Paragraph(escape(line["sku"])+" GST "+escape(line["gst_rate"])+"%: CGST "+amount(line["cgst_minor"])+" / SGST "+amount(line["sgst_minor"])+" / IGST "+amount(line["igst_minor"]),small))
    total_label = "Recorded refund: " if is_return else "Original total: " if bill.get("refund_minor",0)>0 else "Total: "
    story += [table,Spacer(1,20),Paragraph("<b>"+total_label+amount(bill["total_minor"])+"</b>",ParagraphStyle("total",parent=right,fontSize=16,leading=22))]
    if not is_return and bill.get("refund_minor",0)>0:
        story += [Spacer(1,8),Paragraph("Recorded refunds: "+amount(bill["refund_minor"]),right),Paragraph("Remaining sales amount: "+amount(bill["net_total_minor"]),right)]
    story += [Spacer(1,28),Paragraph("Return saved against the original bill." if is_return else "Thank you for your purchase.",normal),Spacer(1,5),Paragraph("Refund payment is handled separately by the store." if is_return else "Itemized sales receipt. GST calculation is based on shop settings; this is not a GST filing or e-invoice service.",small)]
    def footer(canvas,doc):
        canvas.setFont("RetailFont",8);canvas.setFillColor(muted)
        canvas.drawString(42,24,"RetailPulse | "+("Return record" if is_return else "Sales receipt"))
        canvas.drawRightString(A4[0]-42,24,f"Page {doc.page}")
    document.build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()


def return_pdf(record):
    bill = {**record,"total_minor":record["refund_minor"],
            "items":[{**line,"line_total_minor":line["refund_minor"]} for line in record["items"]]}
    return receipt_pdf(bill,record_type=record["kind"])
