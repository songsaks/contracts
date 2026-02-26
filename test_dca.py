quantity = 1000
entry_price = 17.45
current_price = 13.50

gain_loss_pct = (current_price - entry_price) / entry_price * 100
print(f"Loss: {gain_loss_pct}")

target_cost = current_price / 0.90
print(f"Target Cost (-10% loss): {target_cost}")

dca_qty = quantity * (entry_price - target_cost) / (target_cost - current_price)
dca_amount = dca_qty * current_price

print(f"Need to buy {dca_qty} shares at {current_price} (Total {dca_amount}) to reach {target_cost} avg cost.")

new_avg = (quantity * entry_price + dca_qty * current_price) / (quantity + dca_qty)
print(f"New Avg check: {new_avg}")

