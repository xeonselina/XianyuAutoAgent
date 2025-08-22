/**
 * 甘特图JavaScript逻辑
 */

class GanttChart {
    constructor() {
        this.currentDate = new Date();
        this.startDate = new Date();
        this.endDate = new Date();
        this.devices = [];
        this.rentals = [];
        this.availableSlot = null;
        
        // 日历相关
        this.calendarDate = new Date();
        this.selectedStartDate = null;
        this.selectedEndDate = null;
        this.isSelectingEnd = false;
        
        this.init();
    }
    
    init() {
        this.setupDateRange();
        this.loadData();
        this.setupEventListeners();
        this.updateStats();
    }
    
    setupDateRange() {
        // 设置默认显示当前月
        const today = new Date();
        this.startDate = new Date(today.getFullYear(), today.getMonth(), 1);
        this.endDate = new Date(today.getFullYear(), today.getMonth() + 1, 0);
        this.currentDate = today;
        
        this.updateDateNavigation();
    }
    
    getMonthEndDate(year, month) {
        // 获取指定年月的最后一天
        return new Date(year, month + 1, 0);
    }
    
    getMonthStartDate(year, month) {
        // 获取指定年月的第一天
        return new Date(year, month, 1);
    }
    
    setupEventListeners() {
        // 设置日期输入框的默认值
        document.getElementById('query-start-date').value = this.formatDate(this.startDate);
        document.getElementById('query-end-date').value = this.formatDate(this.endDate);
        
        // 监听收件信息变化，自动提取手机号
        this.setupShippingInfoListener();
    }
    
    async loadData() {
        try {
            const response = await axios.get('/api/gantt/data', {
                params: {
                    start_date: this.formatDate(this.startDate),
                    end_date: this.formatDate(this.endDate)
                }
            });
            
            if (response.data.success) {
                this.devices = response.data.data.devices;
                this.rentals = response.data.data.rentals;
                this.renderGantt();
                this.updateStats();
                this.populateFilters();
            } else {
                console.error('加载数据失败:', response.data.error);
            }
        } catch (error) {
            this.showToast('加载数据异常: ' + this.getErrorMessage(error), 'error');
            console.error('加载数据异常:', error);
        }
    }
    
    renderGantt() {
        const container = document.getElementById('gantt-chart');
        container.innerHTML = '';
        
        // 创建甘特图
        this.createHeader(container);
        this.createRows(container);
    }
    
    createHeader(container) {
        const header = document.createElement('div');
        header.className = 'gantt-header';
        
        const headerRow = document.createElement('div');
        headerRow.className = 'gantt-row';
        
        // 设备列标题
        const deviceHeader = document.createElement('div');
        deviceHeader.className = 'gantt-cell gantt-device-cell';
        deviceHeader.innerHTML = '<strong>设备</strong>';
        headerRow.appendChild(deviceHeader);
        
        // 日期列标题
        const currentDate = new Date(this.startDate);
        while (currentDate <= this.endDate) {
            const dateHeader = document.createElement('div');
            dateHeader.className = 'gantt-cell gantt-date-cell';
            
            // 检查是否是今天
            if (this.isToday(currentDate)) {
                dateHeader.className += ' gantt-today';
            }
            
            dateHeader.innerHTML = `
                <div>${this.formatDateHeader(currentDate)}</div>
            `;
            headerRow.appendChild(dateHeader);
            
            currentDate.setDate(currentDate.getDate() + 1);
        }
        
        header.appendChild(headerRow);
        container.appendChild(header);
    }
    
    createRows(container) {
        this.devices.forEach(device => {
            const row = document.createElement('div');
            row.className = 'gantt-row';
            
            // 设备信息列
            const deviceCell = document.createElement('div');
            deviceCell.className = `gantt-cell gantt-device-cell device-status-${device.status}`;
            deviceCell.setAttribute('data-device-id', device.id);
            deviceCell.innerHTML = `
                <div>
                    <div><strong>${device.name}</strong></div>
                    <div style="font-size: 0.7em; color: #6c757d;">
                        编号: ${device.serial_number || 'N/A'}
                    </div>
                    <div style="margin-top: 5px;">
                        <select class="form-select form-select-sm device-status-select" 
                                data-device-id="${device.id}" 
                                onchange="ganttChart.updateDeviceStatus(${device.id}, this.value)">
                            <option value="idle" ${device.status === 'idle' ? 'selected' : ''}>空闲</option>
                            <option value="pending_ship" ${device.status === 'pending_ship' ? 'selected' : ''}>待寄出</option>
                            <option value="renting" ${device.status === 'renting' ? 'selected' : ''}>租赁中</option>
                            <option value="pending_return" ${device.status === 'pending_return' ? 'selected' : ''}>待寄回</option>
                            <option value="returned" ${device.status === 'returned' ? 'selected' : ''}>已寄回</option>
                            <option value="offline" ${device.status === 'offline' ? 'selected' : ''}>下架</option>
                        </select>
                    </div>
                </div>
            `;
            row.appendChild(deviceCell);
            
            // 日期列
            const currentDate = new Date(this.startDate);
            while (currentDate <= this.endDate) {
                const dateCell = document.createElement('div');
                dateCell.className = 'gantt-cell';
                
                // 检查是否有租赁记录（扩展到寄出-收回时间）
                const rental = this.getRentalForDeviceAndDate(device.id, currentDate);
                if (rental) {
                    const el = this.createOccupancyElement(rental, currentDate);
                    if (el) dateCell.appendChild(el);
                } else if (device.status === 'available') {
                    dateCell.className += ' available';
                }
                
                row.appendChild(dateCell);
                currentDate.setDate(currentDate.getDate() + 1);
            }
            
            container.appendChild(row);
        });
    }
    
    // 计算寄出/收回时间（优先使用后端提供字段）
    getShipOutDate(rental) {
        if (rental.ship_out_time) {
            return new Date(rental.ship_out_time);
        }
        const startDate = new Date(rental.start_date);
        const logisticsDays = 1; // 兜底：老数据没有物流天数则按1天
        const shipOut = new Date(startDate);
        shipOut.setDate(shipOut.getDate() - 1 - logisticsDays);
        return shipOut;
    }
    
    getShipInDate(rental) {
        if (rental.ship_in_time) {
            return new Date(rental.ship_in_time);
        }
        const endDate = new Date(rental.end_date);
        const logisticsDays = 1;
        const shipIn = new Date(endDate);
        shipIn.setDate(shipIn.getDate() + 1 + logisticsDays);
        return shipIn;
    }
    
    // 在单元格内渲染占用条（外层：寄出-收回；内层：租赁期间）
    createOccupancyElement(rental, currentDate) {
        const dayStr = this.formatDate(currentDate);
        const shipOut = this.getShipOutDate(rental);
        const shipIn = this.getShipInDate(rental);
        const startDate = new Date(rental.start_date);
        const endDate = new Date(rental.end_date);
        
        const inFullRange = this.formatDate(shipOut) <= dayStr && dayStr <= this.formatDate(shipIn);
        if (!inFullRange) return null;
        
        const inRentalRange = this.formatDate(startDate) <= dayStr && dayStr <= this.formatDate(endDate);
        
        const wrap = document.createElement('div');
        wrap.className = 'gantt-occupy';
        
        // 使用随机颜色而不是固定的灰色
        const rentalColor = this.getRentalColor(rental.id);
        wrap.style.backgroundColor = rentalColor;
        wrap.style.opacity = '0.8';
        wrap.style.position = 'relative';
        wrap.style.zIndex = '1';
        
        if (inRentalRange) {
            const inner = document.createElement('div');
            inner.className = 'gantt-occupy-inner';
            
            // 在租赁时间段显示客户姓名
            inner.textContent = rental.customer_name;
            
            // 在租赁时间段添加编辑按钮
            const editBtn = document.createElement('button');
            editBtn.className = 'edit-btn';
            editBtn.innerHTML = '<i class="bi bi-pencil"></i>';
            editBtn.title = '编辑租赁记录';
            editBtn.onclick = (e) => {
                e.stopPropagation();
                this.editRental(rental);
            };
            inner.appendChild(editBtn);
            
            // 在租赁时间段添加删除按钮
            const deleteBtn = document.createElement('button');
            deleteBtn.className = 'delete-btn';
            deleteBtn.innerHTML = '<i class="bi bi-trash"></i>';
            deleteBtn.title = '删除租赁记录';
            deleteBtn.onclick = (e) => {
                e.stopPropagation();
                this.deleteRental(rental.id);
            };
            inner.appendChild(deleteBtn);
            
            wrap.appendChild(inner);
        }
        
        // 添加悬停提示信息
        const tooltip = this.createRentalInfoElement(rental, shipOut, shipIn);
        let hideTimeout;
        let isTooltipVisible = false;
        let isMouseOverTooltip = false;
        
        const showTooltip = () => {
            if (!isTooltipVisible) {
                clearTimeout(hideTimeout);
                document.body.appendChild(tooltip);
                const rect = wrap.getBoundingClientRect();
                tooltip.style.left = `${rect.left}px`;
                tooltip.style.top = `${rect.bottom + 5}px`;
                tooltip.style.display = 'block';
                tooltip.style.pointerEvents = 'auto';
                isTooltipVisible = true;
            }
        };
        
        const hideTooltip = () => {
            if (isTooltipVisible && !isMouseOverTooltip) {
                tooltip.style.display = 'none';
                tooltip.style.pointerEvents = 'none';
                if (tooltip.parentNode) {
                    tooltip.parentNode.removeChild(tooltip);
                }
                isTooltipVisible = false;
            }
        };
        
        // 租赁时段的鼠标事件
        wrap.addEventListener('mouseenter', () => {
            clearTimeout(hideTimeout);
            showTooltip();
        });
        
        wrap.addEventListener('mouseleave', () => {
            hideTimeout = setTimeout(() => {
                hideTooltip();
            }, 300); // 增加延迟时间
        });
        
        // 弹出层的鼠标事件
        tooltip.addEventListener('mouseenter', () => {
            clearTimeout(hideTimeout);
            isMouseOverTooltip = true;
        });
        
        tooltip.addEventListener('mouseleave', () => {
            isMouseOverTooltip = false;
            hideTooltip();
        });
        
        return wrap;
    }
    
    createCompleteRentalElements(rental, currentDate) {
        const elements = [];
        const currentDateStr = this.formatDate(currentDate);
        
        // 确保日期是Date对象
        const startDate = new Date(rental.start_date);
        const endDate = new Date(rental.end_date);
        
        // 计算寄出时间和收回时间
        const logisticsDays = 1; // 默认物流时间1天，可以根据实际情况调整
        const shipOutDate = new Date(startDate);
        shipOutDate.setDate(shipOutDate.getDate() - 1 - logisticsDays);
        
        const shipInDate = new Date(endDate);
        shipInDate.setDate(shipInDate.getDate() + 1 + logisticsDays);
        
        // 检查当前日期是否在寄出到收回的时间范围内
        if (currentDateStr >= this.formatDate(shipOutDate) && currentDateStr <= this.formatDate(shipInDate)) {
            const rentalElement = document.createElement('div');
            
            // 判断当前日期属于哪个时间段
            if (currentDateStr >= this.formatDate(shipOutDate) && currentDateStr < this.formatDate(startDate)) {
                // 寄出物流时间
                rentalElement.className = 'gantt-rental logistics-time';
                rentalElement.textContent = '寄出';
            } else if (currentDateStr >= this.formatDate(startDate) && currentDateStr <= this.formatDate(endDate)) {
                // 租赁时间
                rentalElement.className = 'gantt-rental rental-time';
                rentalElement.textContent = rental.customer_name;
            } else {
                // 收回物流时间
                rentalElement.className = 'gantt-rental logistics-time';
                rentalElement.textContent = '收回';
            }
            
            // 添加悬停提示信息
            rentalElement.appendChild(this.createRentalInfoElement(rental, shipOutDate, shipInDate));
            
            // 添加删除按钮（只在租赁时间显示）
            if (currentDateStr >= this.formatDate(startDate) && currentDateStr <= this.formatDate(endDate)) {
                const deleteBtn = document.createElement('button');
                deleteBtn.className = 'delete-btn';
                deleteBtn.innerHTML = '<i class="bi bi-trash"></i>';
                deleteBtn.onclick = (e) => {
                    e.stopPropagation();
                    this.deleteRental(rental.id);
                };
                rentalElement.appendChild(deleteBtn);
            }
            
            elements.push(rentalElement);
        }
        
        return elements;
    }
    
    createRentalInfoElement(rental, shipOutDate, shipInDate) {
        const infoDiv = document.createElement('div');
        infoDiv.className = 'rental-info';
        infoDiv.style.position = 'fixed';
        infoDiv.style.background = 'white';
        infoDiv.style.border = '1px solid #dee2e6';
        infoDiv.style.borderRadius = '4px';
        infoDiv.style.padding = '8px';
        infoDiv.style.boxShadow = '0 2px 8px rgba(0,0,0,0.15)';
        infoDiv.style.zIndex = '99999';
        infoDiv.style.minWidth = '250px';
        infoDiv.style.whiteSpace = 'nowrap';
        infoDiv.style.display = 'none';
        infoDiv.style.pointerEvents = 'none';
        
        const logisticsDays = 1; // 默认物流时间1天
        
        infoDiv.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; border-bottom: 1px solid #dee2e6; padding-bottom: 8px;">
                <strong style="color: #495057;">租赁信息</strong>
                <div style="display: flex; gap: 5px;">
                    <button type="button" class="btn btn-sm btn-success rental-contract-btn" 
                            onclick="ganttChart.viewRentalContract(${rental.id})"
                            style="font-size: 12px; padding: 2px 8px;">
                        <i class="bi bi-file-earmark-text"></i> 租赁合同
                    </button>
                    <button type="button" class="btn btn-sm btn-primary shipping-order-btn" 
                            onclick="ganttChart.viewShippingOrder(${rental.id})"
                            style="font-size: 12px; padding: 2px 8px;">
                        <i class="bi bi-file-earmark-text"></i> 出货单
                    </button>
                </div>
            </div>
            <div class="info-row">
                <span class="info-label">客户名:</span>
                <span class="info-value">${rental.customer_name}</span>
            </div>
            <div class="info-row">
                <span class="info-label">联系方式:</span>
                <span class="info-value">${rental.customer_phone || 'N/A'}</span>
            </div>
            <div class="info-row">
                <span class="info-label">寄出时间:</span>
                <span class="info-value">${this.formatDate(shipOutDate)}</span>
            </div>
            <div class="info-row">
                <span class="info-label">租赁开始:</span>
                <span class="info-value">${this.formatDate(new Date(rental.start_date))}</span>
            </div>
            <div class="info-row">
                <span class="info-label">租赁结束:</span>
                <span class="info-value">${this.formatDate(new Date(rental.end_date))}</span>
            </div>
            <div class="info-row">
                <span class="info-label">收回时间:</span>
                <span class="info-value">${this.formatDate(shipInDate)}</span>
            </div>
            <div class="info-row">
                <span class="info-label">寄出运单:</span>
                <span class="info-value">${rental.ship_out_tracking_no || 'N/A'}</span>
            </div>
            <div class="info-row">
                <span class="info-label">寄回运单:</span>
                <span class="info-value">${rental.ship_in_tracking_no || 'N/A'}</span>
            </div>
            <div class="info-row">
                <span class="info-label">目的地:</span>
                <span class="info-value">${rental.destination || 'N/A'}</span>
            </div>
        `;
        
        return infoDiv;
    }
    
    async deleteRental(rentalId) {
        if (!confirm('确定要删除这个租赁记录吗？此操作不可恢复。')) {
            return;
        }
        
        try {
            const response = await axios.delete(`/web/rentals/${rentalId}`);
            
            if (response.data.success) {
                this.showToast('租赁记录删除成功', 'success');
                // 刷新甘特图数据
                this.loadData();
            } else {
                this.showToast('删除失败: ' + response.data.error, 'error');
            }
        } catch (error) {
            this.showToast('删除失败: ' + this.getErrorMessage(error), 'error');
        }
    }
    
    editRental(rental) {
        // 填充编辑表单
        document.getElementById('edit-rental-id').value = rental.id;
        document.getElementById('edit-start-date').value = (typeof rental.start_date === 'string') ? rental.start_date : this.formatDate(new Date(rental.start_date));
        document.getElementById('edit-end-date').value = (typeof rental.end_date === 'string') ? rental.end_date : this.formatDate(new Date(rental.end_date));
        document.getElementById('edit-customer-name').value = rental.customer_name;
        document.getElementById('edit-customer-phone').value = rental.customer_phone || '';
        document.getElementById('edit-shipping-info').value = rental.destination || '';
        document.getElementById('edit-ship-out-tracking').value = rental.ship_out_tracking_no || '';
        document.getElementById('edit-ship-in-tracking').value = rental.ship_in_tracking_no || '';
        
        // 显示编辑模态框
        const modal = new bootstrap.Modal(document.getElementById('editRentalModal'));
        modal.show();
    }
    
    async updateRental() {
        const rentalId = document.getElementById('edit-rental-id').value;
        const formData = {
            end_date: document.getElementById('edit-end-date').value,
            customer_phone: document.getElementById('edit-customer-phone').value,
            destination: document.getElementById('edit-shipping-info').value,
            ship_out_tracking_no: document.getElementById('edit-ship-out-tracking').value,
            ship_in_tracking_no: document.getElementById('edit-ship-in-tracking').value
        };
        
        try {
            const response = await axios.put(`/web/rentals/${rentalId}`, formData);
            
            if (response.data.success) {
                this.showToast('租赁记录更新成功', 'success');
                
                // 关闭模态框
                const modal = bootstrap.Modal.getInstance(document.getElementById('editRentalModal'));
                modal.hide();
                
                // 刷新数据
                this.loadData();
            } else {
                this.showToast('更新失败: ' + response.data.error, 'error');
            }
        } catch (error) {
            this.showToast('更新失败: ' + this.getErrorMessage(error), 'error');
        }
    }
    
    // 重写：在寄出-收回范围内判断有无记录
    getRentalForDeviceAndDate(deviceId, date) {
        const dateStr = this.formatDate(date);
        return this.rentals.find(rental => {
            if (rental.device_id !== deviceId) return false;
            if (rental.status === 'cancelled') return false;
            const shipOutStr = this.formatDate(this.getShipOutDate(rental));
            const shipInStr = this.formatDate(this.getShipInDate(rental));
            return shipOutStr <= dateStr && dateStr <= shipInStr;
        });
    }
    
    // 为 rental 生成随机颜色
    getRentalColor(rentalId) {
        // 如果已经有颜色，直接返回
        if (this.rentalColors && this.rentalColors[rentalId]) {
            return this.rentalColors[rentalId];
        }
        
        // 初始化颜色映射
        if (!this.rentalColors) {
            this.rentalColors = {};
        }
        
        // 预定义一组美观的颜色
        const colors = [
            '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7',
            '#DDA0DD', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9',
            '#F8C471', '#82E0AA', '#F1948A', '#85C1E9', '#D7BDE2',
            '#A9CCE3', '#F9E79F', '#D5A6BD', '#A3E4D7', '#FAD7A0'
        ];
        
        // 为这个 rental 分配一个颜色
        const colorIndex = Object.keys(this.rentalColors).length % colors.length;
        this.rentalColors[rentalId] = colors[colorIndex];
        
        return this.rentalColors[rentalId];
    }
    
    openBookingModal() {
        // 重置表单和状态
        document.getElementById('bookingForm').reset();
        document.getElementById('submit-booking-btn').disabled = true;
        this.availableSlot = null;
        
        // 重置日历选择
        this.resetCalendarSelection();
        
        // 设置默认物流时间
        document.getElementById('logistics-days').value = '1';
        
        // 显示模态框
        const modal = new bootstrap.Modal(document.getElementById('bookingModal'));
        modal.show();
        
        // 模态框显示后渲染日历
        setTimeout(() => {
            this.renderCalendar();
        }, 100);
    }
    
    async findAvailableSlot() {
        if (!this.selectedStartDate || !this.selectedEndDate) {
            this.showToast('请先在日历中选择租赁开始和结束日期', 'error');
                return;
            }
            
        const logisticsDays = parseInt(document.getElementById('logistics-days').value);
        
        if (!logisticsDays || logisticsDays < -1) {
            this.showToast('物流时间不能少于-1天', 'error');
            return;
        }
        
        // 验证日期 - 允许开始和结束日期是同一天
        if (this.selectedStartDate > this.selectedEndDate) {
            this.showToast('开始日期不能晚于结束日期', 'error');
            return;
        }
        
        try {
            // 调用后端API查找档期
            const response = await axios.post('/api/rentals/find-slot', {
                start_date: this.formatDate(this.selectedStartDate),
                end_date: this.formatDate(this.selectedEndDate),
                logistics_days: logisticsDays
            });
            
            if (response.data.success) {
                const data = response.data.data;
                this.availableSlot = {
                    device: data.device,
                    shipOutDate: new Date(data.ship_out_date),
                    shipInDate: new Date(data.ship_in_date)
                };
                
                document.getElementById('submit-booking-btn').disabled = false;
                this.showToast(data.message, 'success');
            } else {
                this.showToast(response.data.error, 'error');
                document.getElementById('submit-booking-btn').disabled = true;
            }
        } catch (error) {
            if (error.response && error.response.status === 404) {
                this.showToast('未找到可用档期，请调整时间或物流时间', 'error');
            } else {
                this.showToast('查找档期失败: ' + this.getErrorMessage(error), 'error');
            }
            document.getElementById('submit-booking-btn').disabled = true;
        }
    }
    
    async submitBooking() {
        if (!this.selectedStartDate || !this.selectedEndDate) {
            this.showToast('请先选择租赁开始和结束日期', 'error');
            return;
        }
        
        const formData = {
            device_id: this.availableSlot.device.id,
            start_date: this.formatDate(this.selectedStartDate),
            end_date: this.formatDate(this.selectedEndDate),
            customer_name: document.getElementById('customer-name').value,
            customer_phone: document.getElementById('customer-phone').value,
            destination: document.getElementById('shipping-info').value,
            ship_out_time: this.formatDate(this.availableSlot.shipOutDate),
            ship_in_time: this.formatDate(this.availableSlot.shipInDate)
        };
        
        try {
            const response = await axios.post('/api/rentals', formData);
            
            if (response.data.success) {
                this.showToast('预定成功！', 'success');
                
                // 关闭模态框
                const modal = bootstrap.Modal.getInstance(document.getElementById('bookingModal'));
                modal.hide();
                
                // 刷新数据
                this.loadData();
                
                // 清空表单和日历选择
                document.getElementById('bookingForm').reset();
                document.getElementById('submit-booking-btn').disabled = true;
                this.availableSlot = null;
                this.resetCalendarSelection();
            } else {
                this.showToast('创建失败: ' + response.data.error, 'error');
            }
        } catch (error) {
            this.showToast('创建失败: ' + this.getErrorMessage(error), 'error');
        }
    }
    
    setupShippingInfoListener() {
        // 监听收件信息输入框变化
        const shippingInfoInput = document.getElementById('shipping-info');
        if (shippingInfoInput) {
            shippingInfoInput.addEventListener('input', (e) => {
                this.autoExtractPhoneNumber(e.target.value);
            });
        }
        
        // 监听编辑模态框中的收件信息变化
        const editShippingInfoInput = document.getElementById('edit-shipping-info');
        if (editShippingInfoInput) {
            editShippingInfoInput.addEventListener('input', (e) => {
                this.autoExtractPhoneNumberForEdit(e.target.value);
            });
        }
    }
    
    autoExtractPhoneNumber(shippingInfo) {
        const phoneNumber = this.extractPhoneNumberFromText(shippingInfo);
        if (phoneNumber) {
            const phoneInput = document.getElementById('customer-phone');
            if (phoneInput && !phoneInput.value) {
                phoneInput.value = phoneNumber;
                this.showToast(`已自动提取手机号: ${phoneNumber}`, 'info');
            }
        }
    }
    
    autoExtractPhoneNumberForEdit(shippingInfo) {
        const phoneNumber = this.extractPhoneNumberFromText(shippingInfo);
        if (phoneNumber) {
            const phoneInput = document.getElementById('edit-customer-phone');
            if (phoneInput && !phoneInput.value) {
                phoneInput.value = phoneNumber;
                this.showToast(`已自动提取手机号: ${phoneNumber}`, 'info');
            }
        }
    }
    
    extractPhoneNumberFromText(text) {
        // 匹配中国大陆手机号的正则表达式
        const phoneRegex = /1[3-9]\d{9}/g;
        const matches = text.match(phoneRegex);
        return matches ? matches[0] : null;
    }
    
    getDestinationString() {
        // 这个方法现在返回收件信息文本框的值
        return document.getElementById('shipping-info')?.value || '';
    }
    
    async updateDeviceStatus(deviceId, newStatus) {
        try {
            const response = await axios.put(`/api/devices/${deviceId}`, { status: newStatus });
            
            if (response.data.success) {
                this.showToast(`设备状态已更新为: ${this.getStatusText(newStatus)}`, 'success');
                // 更新本地数据
                const device = this.devices.find(d => d.id === deviceId);
                if (device) {
                    device.status = newStatus;
                }
                // 即时更新设备单元格的颜色类
                const cell = document.querySelector(`.gantt-device-cell[data-device-id="${deviceId}"]`);
                if (cell) {
                    // 移除旧的 device-status-* 类
                    [...cell.classList].forEach(cls => {
                        if (cls.startsWith('device-status-')) cell.classList.remove(cls);
                    });
                    cell.classList.add(`device-status-${newStatus}`);
                }
            } else {
                this.showToast('状态更新失败: ' + response.data.error, 'error');
            }
        } catch (error) {
            this.showToast('状态更新失败: ' + this.getErrorMessage(error), 'error');
        }
    }
    
    async queryInventory() {
        const startDate = document.getElementById('query-start-date').value;
        const endDate = document.getElementById('query-end-date').value;
        const deviceType = document.getElementById('query-device-type').value;
        
        if (!startDate || !endDate) {
            this.showToast('请选择开始和结束日期', 'error');
            return;
        }
        
        try {
            const response = await axios.get('/api/inventory/available', {
                params: {
                    start_date: startDate,
                    end_date: endDate,
                    device_type: deviceType
                }
            });
            
            if (response.data.success) {
                this.displayQueryResults(response.data.data);
            } else {
                this.showToast('查询失败: ' + response.data.error, 'error');
            }
        } catch (error) {
            this.showToast('查询失败: ' + this.getErrorMessage(error), 'error');
        }
    }
    
    displayQueryResults(devices) {
        const resultsDiv = document.getElementById('query-results');
        
        if (devices.length === 0) {
            resultsDiv.innerHTML = '<div class="alert alert-info">在指定时间段内没有可用设备</div>';
            return;
        }
        
        let html = `
            <div class="alert alert-success">
                找到 ${devices.length} 台可用设备
            </div>
            <div class="table-responsive">
                <table class="table table-striped">
                    <thead>
                        <tr>
                            <th>设备名称</th>
                            <th>类型</th>
                            <th>型号</th>
                            <th>日租金</th>
                            <th>位置</th>
                        </tr>
                    </thead>
                    <tbody>
        `;
        
        devices.forEach(device => {
            html += `
                <tr>
                    <td>${device.device_name}</td>
                    <td>${device.device_type}</td>
                    <td>${device.model || 'N/A'}</td>
                    <td>¥${device.daily_rate || 'N/A'}</td>
                    <td>${device.location || 'N/A'}</td>
                </tr>
            `;
        });
        
        html += `
                    </tbody>
                </table>
            </div>
        `;
        
        resultsDiv.innerHTML = html;
    }
    
    updateStats() {
        // 更新统计信息
        document.getElementById('total-devices').textContent = this.devices.length;
        
        // 计算可用设备数（状态为idle的设备）
        const availableCount = this.devices.filter(d => d.status === 'idle').length;
        document.getElementById('available-devices').textContent = availableCount;
        
        // 计算活动租赁数
        const activeCount = this.rentals.filter(r => r.status === 'active').length;
        document.getElementById('active-rentals').textContent = activeCount;
        
        // 计算逾期租赁数
        const today = new Date();
        const overdueCount = this.rentals.filter(r => 
            r.status === 'active' && new Date(r.end_date) < today
        ).length;
        document.getElementById('overdue-rentals').textContent = overdueCount;
    }
    
    populateFilters() {
        // 新的筛选器不需要预填充选项，因为它们是文本输入框
        // 设备名称和租赁人使用文本搜索，设备状态使用预定义的选项
        
        // 填充查询模态框的设备类型（如果存在）
        const queryTypeFilter = document.getElementById('query-device-type');
        if (queryTypeFilter) {
            queryTypeFilter.innerHTML = '<option value="">全部类型</option>';
        }
    }
    
    applyFilters() {
        const deviceName = document.getElementById('device-name-filter').value.toLowerCase();
        const deviceStatus = document.getElementById('device-status-filter').value;
        const customerName = document.getElementById('customer-name-filter').value.toLowerCase();
        
        // 过滤设备
        let filteredDevices = this.devices;
        
        if (deviceName) {
            filteredDevices = filteredDevices.filter(d => 
                d.name.toLowerCase().includes(deviceName) || 
                d.serial_number.toLowerCase().includes(deviceName)
            );
        }
        
        if (deviceStatus) {
            filteredDevices = filteredDevices.filter(d => d.status === deviceStatus);
        }
        
        // 过滤租赁记录（如果指定了租赁人）
        if (customerName) {
            const customerRentals = this.rentals.filter(r => 
                r.customer_name && r.customer_name.toLowerCase().includes(customerName)
            );
            const customerDeviceIds = [...new Set(customerRentals.map(r => r.device_id))];
            filteredDevices = filteredDevices.filter(d => customerDeviceIds.includes(d.id));
        }
        
        // 重新渲染甘特图
        this.devices = filteredDevices;
        this.renderGantt();
    }
    
    clearFilters() {
        document.getElementById('device-name-filter').value = '';
        document.getElementById('device-status-filter').value = '';
        document.getElementById('customer-name-filter').value = '';
        
        // 重新加载所有数据
        this.loadData();
    }
    
    navigateDate(days) {
        // 计算新的开始和结束日期
        const newStartDate = new Date(this.startDate);
        newStartDate.setDate(newStartDate.getDate() + days);
        
        const newEndDate = new Date(this.endDate);
        newEndDate.setDate(newEndDate.getDate() + days);
        
        // 如果跨越月份边界，调整到整月
        if (newStartDate.getMonth() !== newEndDate.getMonth()) {
            const startMonth = newStartDate.getMonth();
            const startYear = newStartDate.getFullYear();
            
            this.startDate = this.getMonthStartDate(startYear, startMonth);
            this.endDate = this.getMonthEndDate(startYear, startMonth);
        } else {
            this.startDate = newStartDate;
            this.endDate = newEndDate;
        }
        
        this.currentDate = new Date(this.startDate);
        this.updateDateNavigation();
        this.loadData();
    }
    
    goToToday() {
        const today = new Date();
        this.startDate = new Date(today.getFullYear(), today.getMonth(), 1);
        this.endDate = new Date(today.getFullYear(), today.getMonth() + 1, 0);
        this.currentDate = today;
        
        this.updateDateNavigation();
        this.loadData();
    }
    
    updateDateNavigation() {
        document.getElementById('current-period').textContent = 
            `${this.formatDate(this.startDate)} 至 ${this.formatDate(this.endDate)}`;
    }
    
    refreshData() {
        this.loadData();
    }
    
    // 工具方法
    formatDate(date) {
        // 使用本地时间，避免 toISOString 带来的时区回退（如 8 小时导致前一天）
        const y = date.getFullYear();
        const m = String(date.getMonth() + 1).padStart(2, '0');
        const d = String(date.getDate()).padStart(2, '0');
        return `${y}-${m}-${d}`;
    }
    
    isToday(date) {
        const today = new Date();
        return date.toDateString() === today.toDateString();
    }
    
    getDayName(date) {
        const days = ['日', '一', '二', '三', '四', '五', '六'];
        return days[date.getDay()];
    }

    // 如：1 日(周五)
    formatDateHeader(date) {
        const day = date.getDate();
        const week = this.getDayName(date);
        return `${day} 日(周${week})`;
    }



    // 填充设备下拉（新增租赁弹窗）
    populateDeviceSelect() {
        const sel = document.getElementById('device-select');
        if (!sel) return;
        const current = sel.value;
        sel.innerHTML = '<option value="">选择设备</option>';
        this.devices.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.id;
            opt.textContent = `${d.name}`;
            sel.appendChild(opt);
        });
        if (current) sel.value = current;
    }




    
    getStatusText(status) {
        const statusMap = {
            'idle': '空闲',
            'pending_ship': '待寄出',
            'renting': '租赁中',
            'pending_return': '待寄回',
            'returned': '已寄回',
            'offline': '下架'
        };
        return statusMap[status] || status;
    }
    
    getRentalStatusText(status) {
        const statusMap = {
            'pending': '待审批',
            'active': '进行中',
            'completed': '已完成',
            'cancelled': '已取消',
            'overdue': '已逾期'
        };
        return statusMap[status] || status;
    }
    
    getErrorMessage(error) {
        try {
            if (error && error.response && error.response.data) {
                const data = error.response.data;
                if (typeof data === 'string') return data;
                return data.error || data.message || data.detail || JSON.stringify(data);
            }
            if (error && error.message) return error.message;
            return '请求失败';
        } catch (e) {
            return '请求失败';
        }
    }
    
    showToast(message, type = 'info') {
        // 简单的提示实现
        const alertClass = type === 'error' ? 'alert-danger' : 
                          type === 'success' ? 'alert-success' : 'alert-info';
        
        const toast = document.createElement('div');
        toast.className = `alert ${alertClass} alert-dismissible fade show position-fixed`;
        toast.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
        toast.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        document.body.appendChild(toast);
        
        // 自动消失
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 5000);
    }

    // 日历相关方法
    renderCalendar() {
        const calendarDays = document.getElementById('calendar-days');
        const currentMonthYear = document.getElementById('current-month-year');
        
        if (!calendarDays || !currentMonthYear) return;
        
        // 更新月份年份显示
        const year = this.calendarDate.getFullYear();
        const month = this.calendarDate.getMonth();
        currentMonthYear.textContent = `${year}年${month + 1}月`;
        
        // 获取当月第一天和最后一天
        const firstDay = new Date(year, month, 1);
        const lastDay = new Date(year, month + 1, 0);
        const firstDayOfWeek = firstDay.getDay();
        const daysInMonth = lastDay.getDate();
        
        // 清空日历
        calendarDays.innerHTML = '';
        
        // 添加上个月的日期
        const prevMonth = new Date(year, month, 0);
        const daysInPrevMonth = prevMonth.getDate();
        for (let i = firstDayOfWeek - 1; i >= 0; i--) {
            const day = document.createElement('div');
            day.className = 'calendar-day other-month';
            day.textContent = daysInPrevMonth - i;
            day.onclick = () => this.selectDate(new Date(year, month - 1, daysInPrevMonth - i));
            calendarDays.appendChild(day);
        }
        
        // 添加当月的日期
        for (let day = 1; day <= daysInMonth; day++) {
            const dayElement = document.createElement('div');
            dayElement.className = 'calendar-day';
            dayElement.textContent = day;
            
            const currentDate = new Date(year, month, day);
            
            // 检查是否是今天
            if (this.isToday(currentDate)) {
                dayElement.classList.add('today');
            }
            
            // 检查是否是已选择的开始日期
            if (this.selectedStartDate && this.isSameDate(currentDate, this.selectedStartDate)) {
                dayElement.classList.add('selected-start');
            }
            
            // 检查是否是已选择的结束日期
            if (this.selectedEndDate && this.isSameDate(currentDate, this.selectedEndDate)) {
                dayElement.classList.add('selected-end');
            }
            
            // 检查是否在选择的范围内
            if (this.selectedStartDate && this.selectedEndDate && 
                currentDate >= this.selectedStartDate && currentDate <= this.selectedEndDate) {
                dayElement.classList.add('in-range');
            }
            
            // 检查是否应该禁用（过去的日期）
            if (currentDate < new Date().setHours(0, 0, 0, 0)) {
                dayElement.classList.add('disabled');
            } else {
                dayElement.onclick = () => this.selectDate(currentDate);
            }
            
            calendarDays.appendChild(dayElement);
        }
        
        // 添加下个月的日期
        const remainingCells = 42 - (firstDayOfWeek + daysInMonth); // 6行7列 = 42
        for (let day = 1; day <= remainingCells; day++) {
            const dayElement = document.createElement('div');
            dayElement.className = 'calendar-day other-month';
            dayElement.textContent = day;
            dayElement.onclick = () => this.selectDate(new Date(year, month + 1, day));
            calendarDays.appendChild(dayElement);
        }
        
        this.updateDateSelectionInfo();
    }
    
    selectDate(date) {
        if (date < new Date().setHours(0, 0, 0, 0)) {
            return; // 不能选择过去的日期
        }
        
        if (!this.isSelectingEnd) {
            // 第一次点击，选择开始日期
            this.selectedStartDate = new Date(date);
            this.selectedEndDate = null;
            this.isSelectingEnd = true;
            this.showToast('请选择结束日期', 'info');
        } else {
            // 第二次点击，选择结束日期
            if (date < this.selectedStartDate) {
                this.showToast('结束日期不能早于开始日期', 'error');
                return;
            }
            
            this.selectedEndDate = new Date(date);
            this.isSelectingEnd = false;
            this.showToast('日期选择完成，可以点击"找档期"按钮', 'success');
        }
        
        this.renderCalendar();
    }
    
    isSameDate(date1, date2) {
        return date1.getFullYear() === date2.getFullYear() &&
               date1.getMonth() === date2.getMonth() &&
               date1.getDate() === date2.getDate();
    }
    
    updateDateSelectionInfo() {
        const startDateSpan = document.getElementById('selected-start-date');
        const endDateSpan = document.getElementById('selected-end-date');
        
        if (startDateSpan) {
            startDateSpan.textContent = this.selectedStartDate ? 
                this.formatDate(this.selectedStartDate) : '未选择';
        }
        
        if (endDateSpan) {
            endDateSpan.textContent = this.selectedEndDate ? 
                this.formatDate(this.selectedEndDate) : '未选择';
        }
    }
    
    previousMonth() {
        this.calendarDate.setMonth(this.calendarDate.getMonth() - 1);
        this.renderCalendar();
    }
    
    nextMonth() {
        this.calendarDate.setMonth(this.calendarDate.getMonth() + 1);
        this.renderCalendar();
    }
    
    resetCalendarSelection() {
        this.selectedStartDate = null;
        this.selectedEndDate = null;
        this.isSelectingEnd = false;
        this.calendarDate = new Date();
        this.renderCalendar();
    }
    
    async viewShippingOrder(rentalId) {
        try {
            this.showToast('正在打开出货单...', 'info');
            
            // 打开出货单页面
            const shippingOrderUrl = `/shipping-order/${rentalId}`;
            const shippingOrderWindow = window.open(shippingOrderUrl, '_blank', 'width=800,height=1000,scrollbars=yes,resizable=yes');
            
            if (shippingOrderWindow) {
                this.showToast('出货单已打开', 'success');
            } else {
                this.showToast('无法打开出货单页面，请检查浏览器弹窗设置', 'warning');
            }
        } catch (error) {
            console.error('打开出货单失败:', error);
            this.showToast('打开出货单失败: ' + this.getErrorMessage(error), 'error');
        }
    }
    
    async viewRentalContract(rentalId) {
        try {
            this.showToast('正在打开租赁合同...', 'info');
            
            // 打开租赁合同页面
            const contractUrl = `/rental-contract/${rentalId}`;
            const contractWindow = window.open(contractUrl, '_blank', 'width=1000,height=800,scrollbars=yes,resizable=yes');
            
            if (contractWindow) {
                this.showToast('租赁合同已打开', 'success');
            } else {
                this.showToast('无法打开租赁合同页面，请检查浏览器弹窗设置', 'warning');
            }
        } catch (error) {
            console.error('打开租赁合同失败:', error);
            this.showToast('打开租赁合同失败: ' + this.getErrorMessage(error), 'error');
        }
    }
}

// 全局变量
let ganttChart;

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    ganttChart = new GanttChart();
});

// 全局函数
function navigateDate(days) {
    ganttChart.navigateDate(days);
}

function goToToday() {
    ganttChart.goToToday();
}

function refreshData() {
    ganttChart.refreshData();
}

function applyFilters() {
    ganttChart.applyFilters();
}

function clearFilters() {
    ganttChart.clearFilters();
}

function openBookingModal() {
    ganttChart.openBookingModal();
}

function submitBooking() {
    ganttChart.submitBooking();
}

function findAvailableSlot() {
    ganttChart.findAvailableSlot();
}

function updateRental() {
    ganttChart.updateRental();
}

function queryInventory() {
    ganttChart.queryInventory();
}

function previousMonth() {
    ganttChart.previousMonth();
}

function nextMonth() {
    ganttChart.nextMonth();
}

function updateDeviceStatus(deviceId, newStatus) {
    ganttChart.updateDeviceStatus(deviceId, newStatus);
}
